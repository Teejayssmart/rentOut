from __future__ import annotations

from datetime import date, timedelta

from celery import shared_task
from django.conf import settings
from django.template import Context, Template
from django.utils import timezone

from notifications.models import (
    DeliveryAttempt,
    NotificationPreference,
    NotificationTemplate,
    OutboundNotification,
)
from notifications.services import send_mail
from propertylist_app.models import Booking, Notification, Room, UserProfile
from propertylist_app.notifications.utils import create_in_app_notification_if_allowed


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


def _render_template_string(tpl: str, ctx: dict) -> str:
    """
    Render a Django-template string like 'Hi {{ room_title }}' using ctx dict.
    """
    if not tpl:
        return ""
    return Template(tpl).render(Context(ctx or {}))


def _enrich_context(ctx: dict) -> dict:
    """
    Make templates like {{ room.title }} work even if we only stored room_id.
    """
    ctx = dict(ctx or {})

    # Ensure common URLs exist
    ctx.setdefault("renew_url", _inbox_link())
    ctx.setdefault("cta_url", _inbox_link())

    # Build nested room dict if template expects {{ room.title }}
    room_id = ctx.get("room_id")
    if room_id and "room" not in ctx:
        room = Room.objects.filter(id=room_id).only("title", "paid_until").first()
        if room:
            ctx["room"] = {
                "title": getattr(room, "title", ""),
                "paid_until": str(getattr(room, "paid_until", "")),
            }

    return ctx




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
                # schedule immediately; your beat task will deliver it
                scheduled_for=timezone.now(),
                context={
                    "room_title": getattr(room, "title", ""),
                    "paid_until": str(getattr(room, "paid_until", "")),
                    "cta_url": _inbox_link(),
                },
            )


def _enrich_context(notif: OutboundNotification, ctx: dict) -> dict:
    """
    Ensure templates that reference nested vars like {{ room.title }} can render.

    Supports:
    - listing.expiring: expects room.title, room.paid_until, renew_url
    """
    ctx = dict(ctx or {})

    # Provide common links if missing
    ctx.setdefault("cta_url", _inbox_link())
    ctx.setdefault("renew_url", _inbox_link())

    # If context has room_id but template expects {{ room.title }} etc
    room_id = ctx.get("room_id")
    if room_id and "room" not in ctx:
        try:
            room = Room.objects.filter(id=room_id).only("title", "paid_until").first()
            if room:
                ctx["room"] = {
                    "title": getattr(room, "title", ""),
                    "paid_until": str(getattr(room, "paid_until", "")),
                }
        except Exception:
            # don't break sending if room lookup fails
            pass

    # If paid_until was stored flat, also map it into room.paid_until when possible
    if "room" in ctx and isinstance(ctx["room"], dict):
        if "paid_until" not in ctx["room"] and ctx.get("paid_until"):
            ctx["room"]["paid_until"] = str(ctx["paid_until"])

    return ctx




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

        # Prefer values stored on OutboundNotification, else load from NotificationTemplate.
        subject = getattr(notif, "subject", None)
        body = getattr(notif, "body", None)

        if not subject or not body:
            tmpl = NotificationTemplate.objects.filter(
                key=notif.template_key,
                is_active=True,
                channel=NotificationTemplate.CHANNEL_EMAIL,
            ).first()

            if tmpl:
                subject = subject or (tmpl.subject or "Notification")
                body = body or (tmpl.body or "You have a new notification.")
            else:
                subject = subject or "Notification"
                body = body or "You have a new notification."

        #  Render {{ ... }} placeholders using notif.context
        ctx = _enrich_context(getattr(notif, "context", None) or {})
        subject = _render_template_string(subject, ctx)
        body = _render_template_string(body, ctx)

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
        Booking.objects.filter(is_deleted=False, canceled_at__isnull=True)
        .filter(end__gte=window_start, end__lte=now)
        .select_related("user", "room")
    )

    template = (
        NotificationTemplate.objects.filter(
            key="booking.completed",
            is_active=True,
            channel=NotificationTemplate.CHANNEL_EMAIL,
        ).first()
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
        already_in_app = Notification.objects.filter(
            user=user,
            type="booking_completed",
            body__icontains=f"(booking_id={booking.id})",
        ).exists()

        if not already_in_app:
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
                        "room_title": room_title,
                        "ended_at": booking.end.isoformat(),
                        "cta_url": _inbox_link(),
                    },
                )

        processed += 1

    return processed