from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Avg, Count
from .models import Message, Notification, MessageThread, Review, Room
from django.utils import timezone
from django.db.models.signals import post_save,pre_save
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

from propertylist_app.services.deep_links import build_absolute_url





def _recalc_room_rating(room: Room):
    """
    Room rating: ONLY tenant -> landlord reviews about the listing/landlord experience.
    Only revealed reviews count.
    """
    now = timezone.now()

    agg = Review.objects.filter(
        Q(booking__room=room) | Q(tenancy__room=room),
        role=Review.ROLE_TENANT_TO_LANDLORD,
        active=True,
        reveal_at__isnull=False,
        reveal_at__lte=now,
    ).aggregate(
        avg=Avg("overall_rating"),
        cnt=Count("id"),
    )

    room.avg_rating = float(agg["avg"] or 0.0)
    room.number_rating = int(agg["cnt"] or 0)
    room.save(update_fields=["avg_rating", "number_rating"])



@receiver(post_save, sender=apps.get_model("propertylist_app", "Review"))
def review_saved_update_room_rating(sender, instance, created, **kwargs):
    room = None
    if getattr(instance, "booking_id", None) and getattr(instance.booking, "room_id", None):
        room = instance.booking.room
    elif getattr(instance, "tenancy_id", None) and getattr(instance.tenancy, "room_id", None):
        room = instance.tenancy.room

    if not room:
        return

    update_room_rating_from_revealed_reviews(room)


@receiver(post_delete, sender=apps.get_model("propertylist_app", "Review"))
def review_deleted_update_room_rating(sender, instance, **kwargs):
    room = None
    if getattr(instance, "booking_id", None) and getattr(instance.booking, "room_id", None):
        room = instance.booking.room
    elif getattr(instance, "tenancy_id", None) and getattr(instance.tenancy, "room_id", None):
        room = instance.tenancy.room

    if not room:
        return

    update_room_rating_from_revealed_reviews(room)





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
    if not created:
        return

    room = instance.room
    owner = getattr(room, "property_owner", None)
    booker = instance.user

    booking_deep_link = f"/app/bookings/{instance.id}"
    booking_full_url = build_absolute_url(booking_deep_link)

    if owner:
        _queue_email(
            user=owner,
            template_key="booking.new",
            context={
                "user": {"first_name": owner.first_name},
                "room_id": room.id,
                "booking_id": instance.id,

                # F2 links
                "deep_link": booking_deep_link,
                "cta_url": booking_full_url,
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

                # F2 links
                "deep_link": booking_deep_link,
                "cta_url": booking_full_url,
            },
        )
        

@receiver(post_save, sender=Message)
def message_created_create_notifications(sender, instance: Message, created, **kwargs):
    if not created:
        return

    thread: MessageThread = instance.thread
    recipients = thread.participants.exclude(pk=instance.sender_id).all()

    notifs = []
    queued_any_email = False

    # Build once (same for all recipients)
    deep_link = f"/app/threads/{thread.id}"
    full_url = build_absolute_url(deep_link)

    for user in recipients:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not getattr(profile, "notify_messages", True):
            continue

        # Eligible recipient exists -> enqueue async email task later (even if template missing/disabled)
        queued_any_email = True

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

                # F2: link fields for the email button
                "deep_link": deep_link,
                "cta_url": full_url,

                # Backwards compatible fields (if your template still uses them)
                "thread_url": full_url,
                "snippet": (instance.body[:200] or ""),
            },
        )

    if notifs:
        Notification.objects.bulk_create(notifs, ignore_conflicts=True)

    # Enqueue once per message if at least one recipient opted-in
    if queued_any_email:
        task_send_new_message_email.delay(instance.id)
        
        
# -------------------------------------------------------------------
# TenancyExtension -> Notifications (proposal / accept / reject)
# -------------------------------------------------------------------




def _ext_other_party(ext):
    """
    Returns the user who should be notified when an extension is proposed.
    If landlord proposed -> notify tenant.
    If tenant proposed -> notify landlord.
    """
    t = ext.tenancy
    if ext.proposed_by_id == getattr(t, "landlord_id", None):
        return t.tenant
    return t.landlord


@receiver(pre_save, sender=apps.get_model("propertylist_app", "TenancyExtension"))
def tenancy_extension_cache_old_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._old_status = None
        return
    old = sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    instance._old_status = old


@receiver(post_save, sender=apps.get_model("propertylist_app", "TenancyExtension"))
def tenancy_extension_notifications(sender, instance, created, **kwargs):
    Notification = apps.get_model("propertylist_app", "Notification")

    # safety: tenancy must exist
    if not getattr(instance, "tenancy_id", None):
        return

    t = instance.tenancy

    # 1) created -> proposal notification to the other party
    if created:
        other = _ext_other_party(instance)
        Notification.objects.create(
            user=other,
            type="tenancy_extension_proposed",
            title="Tenancy extension proposed",
            body=f"A tenancy extension was proposed for {t.room.title}.",
            target_type="tenancy_extension",
            target_id=t.id
        )
        return

    # 2) status changed -> accept/reject notifications
    old = getattr(instance, "_old_status", None)
    new = instance.status
    if old == new:
        return

    if new == instance.STATUS_ACCEPTED:
        # notify both
        Notification.objects.create(
            user=t.landlord,
            type="tenancy_extension_accepted",
            title="Tenancy extension accepted",
            body=f"The tenancy extension for {t.room.title} was accepted.",
            target_type="tenancy_extension",
            target_id=t.id,
        )
        Notification.objects.create(
            user=t.tenant,
            type="tenancy_extension_accepted",
            title="Tenancy extension accepted",
            body=f"The tenancy extension for {t.room.title} was accepted.",
            target_type="tenancy_extension",
            target_id=t.id,
        )

    elif new == instance.STATUS_REJECTED:
        # notify proposer only (so they know it was rejected)
        Notification.objects.create(
            user=instance.proposed_by,
            type="tenancy_extension_rejected",
            title="Tenancy extension rejected",
            body=f"The tenancy extension for {t.room.title} was rejected.",
            target_type="tenancy_extension",
            target_id=t.id,
        )
