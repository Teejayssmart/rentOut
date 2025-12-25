from __future__ import annotations
from datetime import date,timedelta
from typing import Optional

from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from celery import shared_task
from propertylist_app.notifications.utils import build_frontend_inbox_link
from propertylist_app.models import Room, Message, Notification, UserProfile,Booking


def expire_paid_listings(today: Optional[date] = None) -> int:
    """
    Hide rooms whose paid_until is in the past and notify the owner.
    Returns the count of rooms affected.
    """
    today = today or timezone.localdate()
    # Lock in a transaction to avoid partial updates
    with transaction.atomic():
        to_hide = (
            Room.objects
            .filter(paid_until__isnull=False, paid_until__lt=today, status="active", is_deleted=False)
            .select_related("property_owner")
        )

        updated_count = 0
        for room in to_hide:
            room.status = "hidden"
            room.save(update_fields=["status"])
            # Create a lightweight notification
            try:
                profile, _ = UserProfile.objects.get_or_create(user=room.property_owner)

                # Respect Account -> Notifications -> Reminders toggle
                if getattr(profile, "notify_reminders", True):
                    Notification.objects.create(
                        user=room.property_owner,
                        type="listing_expired",
                        title="Your listing has expired",
                        body=f"Room '{room.title}' is now hidden because the payment period ended.",
                    )
            except Exception:
                # Never let a notification failure block the job
                pass

            updated_count += 1

        return updated_count


def send_new_message_email(message_id: int) -> int:
    """
    Send a simple email to the other participant in the message thread.
    Returns 1 if sent, 0 otherwise.
    """
    try:
        msg = Message.objects.select_related("thread", "sender").get(pk=message_id)
    except Message.DoesNotExist:
        return 0

    # Determine recipient: the other participant in a 2-person thread
    participants = list(msg.thread.participants.all())
    if len(participants) != 2:
        return 0

    recipient = participants[0] if participants[1].id == msg.sender_id else participants[1]
    if not recipient.email:
        return 0

    subject = f"New message from {msg.sender.username}"
    body = (
        f"You have a new message in your RentOut inbox.\n\n"
        f"From: {msg.sender.username}\n"
        f"Message: {msg.body}\n"
        f"\nLog in to reply."
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")

    try:
        sent = send_mail(subject, body, from_email, [recipient.email], fail_silently=True)
        return int(bool(sent))
    except Exception:
        return 0



@shared_task
def notify_upcoming_bookings(hours_ahead: int = 24):
    now = timezone.now()
    window_end = now + timedelta(hours=hours_ahead)

    qs = (
        Booking.objects
        .filter(is_deleted=False, canceled_at__isnull=True)
        .filter(start__gte=now, start__lte=window_end)
        .select_related("user", "room")
    )

    for booking in qs:
        user = getattr(booking, "user", None)
        if not user:
            continue

        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not getattr(profile, "notify_reminders", True):
            continue

        room = getattr(booking, "room", None)
        room_title = getattr(room, "title", "your room")

        start_local = timezone.localtime(booking.start)
        start_str = start_local.strftime("%d %b %Y, %H:%M")

        title = "Upcoming booking"
        body = f"Reminder: your booking for '{room_title}' starts on {start_str}. (booking_id={booking.id})"

        # Create in-app notification ONCE
        notif, created = Notification.objects.get_or_create(
            user=user,
            type="booking_reminder",
            title=title,
            body=body,
        )

        # Email only when the notification is first created (prevents spam)
        if created:
            inbox_link = build_frontend_inbox_link(tab="notifications")

            # If user email missing, skip safely
            to_email = getattr(user, "email", "") or ""
            if to_email:
                subject = "RentOut reminder: your booking starts soon"
                text = (
                    f"{body}\n\n"
                    f"Open in app: {inbox_link}\n"
                )

                # Simple HTML email with a button
                html = f"""
                <div style="font-family: Arial, sans-serif; line-height: 1.5;">
                  <h2 style="margin: 0 0 12px;">Upcoming booking</h2>
                  <p style="margin: 0 0 12px;">{body}</p>
                  <p style="margin: 18px 0;">
                    <a href="{inbox_link}"
                       style="display:inline-block;padding:10px 14px;background:#356af0;color:#fff;text-decoration:none;border-radius:8px;">
                      Open in RentOut
                    </a>
                  </p>
                  <p style="color:#666;font-size:12px;margin-top:18px;">
                    If you’re not signed in, you’ll be asked to sign in first.
                  </p>
                </div>
                """

                send_mail(
                    subject=subject,
                    message=text,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    recipient_list=[to_email],
                    fail_silently=True,
                    html_message=html,
                )