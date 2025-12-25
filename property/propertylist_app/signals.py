from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Avg, Count

from .models import Message, Notification, MessageThread
from .models import Review, Room


from django.db.models.signals import post_save
from django.dispatch import receiver

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


def _recalc_room_rating(room: Room):
    """
    Room rating is now derived from BOOKING-based reviews.
    """
    agg = Review.objects.filter(
        booking__room=room,
        active=True,
    ).aggregate(
        avg=Avg("overall_rating"),
        cnt=Count("id"),
    )

    room.avg_rating = float(agg["avg"] or 0)
    room.number_rating = int(agg["cnt"] or 0)
    room.save(update_fields=["avg_rating", "number_rating"])


@receiver(post_delete, sender=Review)
def review_deleted(sender, instance: Review, **kwargs):
    room = getattr(getattr(instance, "booking", None), "room", None)
    if room is not None:
        _recalc_room_rating(room)


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


@receiver(post_save, sender=Message)
def message_created_create_notifications(sender, instance: Message, created, **kwargs):
    """
    When a new message is created:
    - create in-app Notification for other participants (respects notify_messages)
    - queue OutboundNotification email for other participants (template_key="message.new")
    """
    if not created:
        return

    thread: MessageThread = instance.thread
    recipients = thread.participants.exclude(pk=instance.sender_id).all()

    notifs = []
    for user in recipients:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not getattr(profile, "notify_messages", True):
            continue

        # in-app notification
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

        # email queue (for celery task to send later)
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

    if notifs:
        Notification.objects.bulk_create(notifs, ignore_conflicts=True)


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