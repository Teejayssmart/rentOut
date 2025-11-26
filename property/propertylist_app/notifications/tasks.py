from datetime import date, timedelta
from django.utils import timezone
from django.conf import settings

from propertylist_app.models import Room
from notifications.models import (
    NotificationTemplate,
    OutboundNotification,
    NotificationPreference,
    DeliveryAttempt,
)
from notifications.services import send_mail


def _render(template_body: str, user) -> str:
    # very small templating for {{ user.first_name }}
    return template_body.replace("{{ user.first_name }}", getattr(user, "first_name", "") or "")


def notify_listing_expiring(days_ahead: int = 3) -> None:
    """
    Queue EMAIL notifications for listings expiring within `days_ahead` days.
    - Uses NotificationTemplate with key="listing.expiring" and is_active=True
    - Creates OutboundNotification rows with status=queued (default)
    """
    template = (
        NotificationTemplate.objects
        .filter(key="listing.expiring", is_active=True, channel=NotificationTemplate.CHANNEL_EMAIL)
        .first()
    )
    if not template:
        return

    cutoff = date.today() + timedelta(days=days_ahead)
    rooms = Room.objects.select_related("property_owner").filter(paid_until__lte=cutoff)

    for room in rooms:
        owner = room.property_owner
        body = _render(template.body, owner)
        OutboundNotification.objects.create(
            user=owner,
            channel=template.CHANNEL_EMAIL,
            template_key=template.key,
            context={"room_id": room.id, "paid_until": str(room.paid_until)},
            scheduled_for=timezone.now(),  # ready to send now
            # status defaults to queued
            # subject is optional in your model and may be blank
            # we keep subject in context and body stores the actual message
        )
        # If you want subject stored separately (optional):
        # obj.subject = template.subject; obj.body = body; obj.save(update_fields=["subject", "body"])


def send_due_notifications() -> None:
    """
    Deliver all queued notifications scheduled up to now.
    Respects NotificationPreference.email_enabled.
    Records DeliveryAttempt and updates OutboundNotification status.
    """
    now = timezone.now()
    qs = OutboundNotification.objects.select_related("user").filter(
        status=OutboundNotification.STATUS_QUEUED,
        scheduled_for__lte=now,
        channel=NotificationTemplate.CHANNEL_EMAIL,
    )

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@rentout.co.uk")

    for notif in qs:
        user = notif.user

        # preference check
        pref = NotificationPreference.objects.filter(user=user).first()
        if not user.email or (pref and not pref.email_enabled):
            notif.status = OutboundNotification.STATUS_SKIPPED
            notif.sent_at = None
            notif.error = "Email disabled or missing address"
            notif.save(update_fields=["status", "sent_at", "error"])
            DeliveryAttempt.objects.create(
                notification=notif, provider="email", success=False, response="skipped: prefs/email"
            )
            continue

        # Build content from stored fields / template
        # If you saved subject/body directly on notif, use those; otherwise render from template.
        subject = getattr(notif, "subject", None) or "Listing expiring soon"
        body = getattr(notif, "body", None)
        if not body:
            tmpl = NotificationTemplate.objects.filter(key=notif.template_key, is_active=True).first()
            raw = tmpl.body if tmpl else "Your listing is expiring soon."
            body = _render(raw, user)

        # send via wrapper (tests patch notifications.services.send_mail)
        result = 0
        try:
            result = send_mail(subject, body, from_email, [user.email])
        except Exception as e:
            notif.status = OutboundNotification.STATUS_FAILED
            notif.error = str(e)
            notif.save(update_fields=["status", "error"])
            DeliveryAttempt.objects.create(
                notification=notif, provider="email", success=False, response=f"exception: {e}"
            )
            continue

        if result > 0:
            notif.status = OutboundNotification.STATUS_SENT
            notif.sent_at = timezone.now()
            notif.error = ""
            notif.save(update_fields=["status", "sent_at", "error"])
            DeliveryAttempt.objects.create(
                notification=notif, provider="email", success=True, response=f"sent:{result}"
            )
        else:
            notif.status = OutboundNotification.STATUS_FAILED
            notif.error = "send_mail returned 0"
            notif.save(update_fields=["status", "error"])
            DeliveryAttempt.objects.create(
                notification=notif, provider="email", success=False, response="returned 0"
            )
