from __future__ import annotations
from datetime import date, timedelta
from django.utils import timezone
from django.conf import settings

from propertylist_app.models import Room, UserProfile,Booking, Notification
from notifications.models import (
    NotificationTemplate,
    OutboundNotification,
    NotificationPreference,
    DeliveryAttempt,
)
from notifications.services import send_mail

from datetime import timedelta
from django.utils import timezone
from celery import shared_task


from propertylist_app.notifications.utils import create_in_app_notification_if_allowed






def _render(template_body: str, user) -> str:
    # very small templating for {{ user.first_name }}
    return template_body.replace("{{ user.first_name }}", getattr(user, "first_name", "") or "")


def _allowed_to_send_template(*, profile: UserProfile, template_key: str) -> bool:
    """
    Maps email templates to Account -> Notifications toggles.
    - marketing templates: require marketing_consent
    - everything else: treated as RentOut updates (notify_rentout_updates)
    """
    key = (template_key or "").strip().lower()

    if key.startswith("marketing_"):
        return bool(getattr(profile, "marketing_consent", False))

    return bool(getattr(profile, "notify_rentout_updates", True))


def notify_listing_expiring(days_ahead: int = 3) -> None:
    """
    Queue EMAIL notifications for listings expiring within `days_ahead` days.
    - Uses NotificationTemplate with key="listing.expiring" and is_active=True
    - Creates OutboundNotification rows with status=queued (default)
    """
    template = (
        NotificationTemplate.objects.filter(
            key="listing.expiring",
            is_active=True,
            channel=NotificationTemplate.CHANNEL_EMAIL,
        ).first()
    )
    if not template:
        return

    cutoff = date.today() + timedelta(days=days_ahead)
    rooms = Room.objects.select_related("property_owner").filter(paid_until__lte=cutoff)

    for room in rooms:
        owner = room.property_owner
        profile, _ = UserProfile.objects.get_or_create(user=owner)

        if _allowed_to_send_template(profile=profile, template_key=template.key):
            OutboundNotification.objects.create(
                user=owner,
                channel=template.CHANNEL_EMAIL,
                template_key=template.key,
                context={"room_id": room.id, "paid_until": str(room.paid_until)},
            )


def _frontend_base_url() -> str:
    """
    Base URL for deep links in emails.
    Use settings.FRONTEND_BASE_URL if you have it, otherwise default to localhost.
    """
    return getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")


def _inbox_link() -> str:
    """
    Deep link to inbox/messages page.
    Adjust the path to match your frontend route when ready.
    """
    return f"{_frontend_base_url()}/inbox"


def _html_email(subject: str, body_text: str, button_url: str, button_text: str = "Open inbox") -> str:
    """
    Simple HTML email with a button.
    """
    safe_body = (body_text or "").replace("\n", "<br>")
    return f"""
    <!doctype html>
    <html>
      <body style="margin:0; padding:0; background:#f6f7fb; font-family: Arial, sans-serif;">
        <div style="max-width:640px; margin:0 auto; padding:24px;">
          <div style="background:#ffffff; border-radius:14px; padding:22px; box-shadow:0 6px 18px rgba(0,0,0,0.06);">
            <h2 style="margin:0 0 12px 0; font-size:18px; color:#111827;">{subject}</h2>
            <p style="margin:0 0 18px 0; font-size:14px; color:#374151; line-height:1.6;">{safe_body}</p>

            <a href="{button_url}"
               style="display:inline-block; padding:12px 16px; border-radius:10px; text-decoration:none;
                      background:#1d4e89; color:#ffffff; font-size:14px;">
              {button_text}
            </a>

            <p style="margin:18px 0 0 0; font-size:12px; color:#6b7280;">
              If the button does not work, copy and paste this link:<br>
              <span style="color:#111827;">{button_url}</span>
            </p>
          </div>
        </div>
      </body>
    </html>
    """.strip()


def send_due_notifications() -> dict:
    """
    Deliver all due notifications scheduled up to now.
    Respects NotificationPreference.email_enabled.
    Records DeliveryAttempt and updates OutboundNotification status.

    Returns a small summary dict for tests/monitoring.
    """
    now = timezone.now()
    qs = (
        OutboundNotification.objects.select_related("user")
        .filter(scheduled_for__lte=now, channel="email")
        .exclude(status__in=[OutboundNotification.STATUS_SENT, OutboundNotification.STATUS_SKIPPED])
    )

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@rentout.co.uk")

    sent_count = 0
    failed_count = 0
    skipped_count = 0

    for notif in qs:
        user = notif.user

        # preference check
        pref = NotificationPreference.objects.filter(user=user).first()
        if not user.email or (pref and not pref.email_enabled):
            skipped_count += 1
            notif.status = OutboundNotification.STATUS_SKIPPED
            notif.sent_at = None
            notif.error = "Email disabled or missing address"
            notif.save(update_fields=["status", "sent_at", "error"])
            DeliveryAttempt.objects.create(
                notification=notif, provider="email", success=False, response="skipped: prefs/email"
            )
            continue

        # Prefer values stored on OutboundNotification, else render from NotificationTemplate.
        subject = getattr(notif, "subject", None)
        body = getattr(notif, "body", None)

        if not subject or not body:
            tmpl = NotificationTemplate.objects.filter(
                key=notif.template_key,
                is_active=True,
                channel=NotificationTemplate.CHANNEL_EMAIL,
            ).first()

            if tmpl:
                if not subject:
                    subject = tmpl.subject or "Listing expiring soon"
                if not body:
                    raw = tmpl.body or "Your listing is expiring soon."
                    body = _render(raw, user)
            else:
                subject = subject or "Listing expiring soon"
                body = body or "Your listing is expiring soon."

        # send via wrapper (tests patch notifications.services.send_mail)
        try:
            html = _html_email(subject, body, _inbox_link())
            result = send_mail(subject, body, from_email, [user.email], html_message=html)
        except Exception as e:
            failed_count += 1
            notif.status = OutboundNotification.STATUS_FAILED
            notif.error = str(e)
            notif.save(update_fields=["status", "error"])
            DeliveryAttempt.objects.create(
                notification=notif, provider="email", success=False, response=f"exception: {e}"
            )
            continue

        if result and result > 0:
            sent_count += 1
            notif.status = OutboundNotification.STATUS_SENT
            notif.sent_at = timezone.now()
            notif.error = ""
            notif.save(update_fields=["status", "sent_at", "error"])
            DeliveryAttempt.objects.create(
                notification=notif, provider="email", success=True, response=f"sent:{result}"
            )
        else:
            failed_count += 1
            notif.status = OutboundNotification.STATUS_FAILED
            notif.error = "send_mail returned 0"
            notif.save(update_fields=["status", "error"])
            DeliveryAttempt.objects.create(
                notification=notif, provider="email", success=False, response="returned 0"
            )

    return {"sent": sent_count, "failed": failed_count, "skipped": skipped_count, "found": qs.count()}





@shared_task
def notify_completed_viewings(hours_back: int = 24) -> int:
    """
    Viewing done = booking ended.

    Creates (only once per booking):
      1) in-app notification (respects notify_confirmations)
      2) queued email OutboundNotification using template key: "booking.completed"

    Returns number of bookings processed.
    """
    now = timezone.now()
    window_start = now - timedelta(hours=hours_back)

    qs = (
        Booking.objects
        .filter(is_deleted=False, canceled_at__isnull=True)
        .filter(end__gte=window_start, end__lte=now)
        .select_related("user", "room")
    )

    template = (
        NotificationTemplate.objects
        .filter(
            key="booking.completed",
            is_active=True,
            channel=NotificationTemplate.CHANNEL_EMAIL,
        )
        .first()
    )

    processed = 0

    for booking in qs:
        user = getattr(booking, "user", None)
        if not user:
            continue

        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not getattr(profile, "notify_confirmations", True):
            continue

        room = getattr(booking, "room", None)
        room_title = getattr(room, "title", "your room")

        end_local = timezone.localtime(booking.end)
        end_str = end_local.strftime("%d %b %Y, %H:%M")

        title = "Viewing completed"
        body = f"Your viewing for '{room_title}' has finished ({end_str}). (booking_id={booking.id})"

        # ---------- 1) IN-APP (dedupe by booking_id) ----------
        # if you ran this before, you may already have duplicates. so we use .exists() not get_or_create().
        already_in_app = Notification.objects.filter(
            user=user,
            type="booking_completed",
            body__icontains=f"(booking_id={booking.id})",
        ).exists()

        if not already_in_app:
            already = Notification.objects.filter(
                user=user,
                type="booking_completed",
                body__icontains=f"(booking_id={booking.id})",
            ).exists()

            if not already:
                create_in_app_notification_if_allowed(
                    user=user,
                    notification_type="booking_completed",
                    title=title,
                    body=body,
                    preference_field="notify_confirmations",
                )


        # ---------- 2) EMAIL QUEUE (dedupe by context.booking_id) ----------
        if template:
            already_queued = OutboundNotification.objects.filter(
                user=user,
                template_key="booking.completed",
                channel=NotificationTemplate.CHANNEL_EMAIL,
                context__booking_id=booking.id,
            ).exists()

            if not already_queued:
                OutboundNotification.objects.create(
                    user=user,
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    template_key="booking.completed",
                    scheduled_for=now,
                    context={
                        "booking_id": booking.id,
                        "room_id": getattr(room, "id", None),
                        "ended_at": booking.end.isoformat(),
                    },
                )

        processed += 1

    return processed

def _render(template_body: str, user) -> str:
    """
    Small templating helper.

    Supports:
    - {{ user.first_name }}
    - {{ user.username }}
    - {{ username }}

    If first_name is missing/blank, falls back to username.
    """
    text = template_body or ""

    first_name = (getattr(user, "first_name", "") or "").strip()
    username = (getattr(user, "username", "") or "").strip() or (getattr(user, "get_username", lambda: "")() or "").strip()

    if not first_name:
        first_name = username

    text = text.replace("{{ user.first_name }}", first_name)
    text = text.replace("{{ user.username }}", username)
    text = text.replace("{{ username }}", username)

    return text
