from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Avg, Count
from .models import Message, Notification, MessageThread, Review, Room
from django.utils import timezone
from django.db.models.signals import post_save
from propertylist_app.models import (
    Review,
    Message,
    MessageThread,
    Notification,
    UserProfile,
    Booking,
)
from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.tasks import task_send_new_message_email
from django.db.models import Avg, Count, Q
from propertylist_app.services.reviews import update_room_rating_from_revealed_reviews
from django.apps import apps




def _recalc_room_rating(room: Room):
    """
    Room rating is derived from both BOOKING-based and TENANCY-based reviews.
    Only revealed reviews count (double-blind / reveal_at reached).
    """
    agg = Review.objects.filter(
        Q(booking__room=room) | Q(tenancy__room=room),
        active=True,
        reveal_at__isnull=False,
        reveal_at__lte=timezone.now(),
    ).aggregate(
        avg=Avg("overall_rating"),
        cnt=Count("id"),
    )

    room.avg_rating = float(agg["avg"] or 0)
    room.number_rating = int(agg["cnt"] or 0)
    room.save(update_fields=["avg_rating", "number_rating"])



@receiver(post_save, sender=apps.get_model("propertylist_app", "Review"))
def review_saved_update_room_rating(sender, instance, created, **kwargs):
    if not getattr(instance, "room_id", None):
        return
    update_room_rating_from_revealed_reviews(instance.room)


@receiver(post_delete, sender=apps.get_model("propertylist_app", "Review"))
def review_deleted_update_room_rating(sender, instance, **kwargs):
    if not getattr(instance, "room_id", None):
        return
    update_room_rating_from_revealed_reviews(instance.room)




def _queue_email(*, user, template_key: str, context: dict | None = None) -> None:
    """
    Queues an email in the notifications app pipeline (does NOT send immediately).
    Only queues if an active email template exists for the key.
    """
    template = NotificationTemplate.objects.filter(
        key=template_key,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        is_active=True,
    ).first()
    if not template:
        return

    OutboundNotification.objects.create(
        user=user,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key=template_key,
        context=context or {},
    )



@receiver(post_save, sender=Booking)
def booking_created_queue_emails(sender, instance: Booking, created, **kwargs):
    """
    When a new booking is created, queue:
    - booking.new email to the room owner
    - booking.confirmation email to the booker
    """
    if not created:
        return

    room = instance.room
    owner = getattr(room, "property_owner", None)
    booker = instance.user

    if owner:
        _queue_email(
            user=owner,
            template_key="booking.new",
            context={
                "user": {"first_name": owner.first_name},
                "room_id": room.id,
                "booking_id": instance.id,
            },
        )

    if booker:
        _queue_email(
            user=booker,
            template_key="booking.confirmation",
            context={
                "user": {"first_name": booker.first_name},
                "room_id": room.id,
                "booking_id": instance.id,
            },
        )
        

@receiver(post_save, sender=Message)
def message_created_create_notifications(sender, instance: Message, created, **kwargs):
    if not created:
        return

    thread: MessageThread = instance.thread
    recipients = thread.participants.exclude(pk=instance.sender_id).all()

    notifs = []
    queued_any_email = False  # <-- add this

    for user in recipients:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not getattr(profile, "notify_messages", True):
            continue

        notifs.append(
            Notification(
                user=user,
                type=Notification.Type.MESSAGE,
                thread=thread,
                message=instance,
                title="New message",
                body=(instance.body[:200] or ""),
            )
        )

        _queue_email(
            user=user,
            template_key="message.new",
            context={
                "user": {"first_name": user.first_name},
                "sender": {"name": instance.sender.get_username()},
                "thread_id": thread.id,
                "message_id": instance.id,
            },
        )
        queued_any_email = True  # <-- add this

    if notifs:
        Notification.objects.bulk_create(notifs, ignore_conflicts=True)

    if queued_any_email:
        task_send_new_message_email.delay(instance.id)  # <-- add this
        