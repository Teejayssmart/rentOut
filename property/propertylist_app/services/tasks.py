from __future__ import annotations
from datetime import date,timedelta
from typing import Optional

from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.conf import settings
from celery import shared_task
from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.services.realtime import push_user_realtime_event
from propertylist_app.models import (
    Room,
    Message,
    MessageThread,
    Notification,
    UserProfile,
    Booking,
)
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.message_threads import (
    get_or_create_canonical_thread,
)

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
                    listing_expired_notification = Notification.objects.create(
                        user=room.property_owner,
                        type="listing_expired",
                        title="Your listing has expired",
                        body=(
                            f"Room '{room.title}' is now hidden because "
                            "the payment period ended."
                        ),
                        audience=Notification.Audience.LANDLORD,
                    )

                    push_user_realtime_event(
                        room.property_owner.id,
                        "new_notification",
                        {
                            "kind": "listing_expired",
                            "notification_id": listing_expired_notification.id,
                            "target_type": "room",
                            "target_id": room.id,
                        },
                    )

                    template_exists = (
                        NotificationTemplate.objects.filter(
                            key="listing.expired",
                            channel=NotificationTemplate.CHANNEL_EMAIL,
                            is_active=True,
                        ).exists()
                    )

                    if template_exists:
                        OutboundNotification.objects.create(
                            user=room.property_owner,
                            channel=NotificationTemplate.CHANNEL_EMAIL,
                            template_key="listing.expired",
                            scheduled_for=timezone.now(),
                            context={
                                "user": {
                                    "first_name": (
                                        room.property_owner.first_name
                                        or room.property_owner.username
                                    ),
                                },
                                "room": {
                                    "id": room.id,
                                    "title": room.title,
                                },
                                "paid_until": (
                                    room.paid_until.isoformat()
                                    if room.paid_until
                                    else ""
                                ),

                                # Mobile app destination.
                                "deep_link": f"/app/listings/{room.id}",

                                # Web/Vercel action button.
                                "cta_url": build_absolute_url(
                                    "/my-listings",
                                    force_login=True,
                                ),
                            },
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

    subject = f"New message from {msg.sender.username} on RentCrib"
    body = (
        "You have a new message on RentCrib.\n\n"
        "Open your conversation to read and reply.\n\n"
        "The message content is only available inside RentCrib."
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")

    try:
        sent = send_mail(subject, body, from_email, [recipient.email], fail_silently=True)
        return int(bool(sent))
    except Exception:
        return 0



@shared_task
def notify_upcoming_bookings(minutes_ahead: int = 5) -> int:
    """
    Queue upcoming-viewing reminders shortly before the viewing starts.

    Temporary staging / QA rule:
    - Reminder becomes eligible 5 minutes before booking.start.

    Production rule:
    - Change Celery Beat args to 60 so reminders are sent 1 hour before viewing.

    Each viewing can generate:
      1) seeker in-app reminder
      2) seeker booking.reminder email
      3) landlord in-app reminder
      4) landlord booking.reminder_landlord email
      5) one shared RentCrib system message in the conversation

    Reminders are deduplicated by booking + current viewing start time,
    so rescheduling the same booking can generate a fresh reminder.
    """
    now = timezone.now()
    window_end = now + timedelta(minutes=minutes_ahead)

    bookings = (
        Booking.objects
        .filter(
            is_deleted=False,
            canceled_at__isnull=True,
            start__gte=now,
            start__lte=window_end,
        )
        .select_related(
            "user",
            "room",
            "room__property_owner",
        )
    )

    seeker_template = (
        NotificationTemplate.objects.filter(
            key="booking.reminder",
            is_active=True,
            channel=NotificationTemplate.CHANNEL_EMAIL,
        ).first()
    )

    landlord_template = (
        NotificationTemplate.objects.filter(
            key="booking.reminder_landlord",
            is_active=True,
            channel=NotificationTemplate.CHANNEL_EMAIL,
        ).first()
    )

    processed = 0

    for booking in bookings:
        seeker = getattr(booking, "user", None)
        room = getattr(booking, "room", None)

        if not seeker or not room:
            continue

        landlord = getattr(room, "property_owner", None)
        room_title = getattr(room, "title", "your property")

        start_local = timezone.localtime(booking.start)
        start_str = start_local.strftime("%d %b %Y, %H:%M")

        seeker_booking_url = build_absolute_url(
            f"/viewings/{booking.id}",
            force_login=False,
        )

        landlord_booking_url = build_absolute_url(
            f"/viewings/{booking.id}",
            force_login=False,
        )

        seeker_name = (
            seeker.get_full_name().strip()
            or seeker.username
            or seeker.first_name
            or "A prospective tenant"
        )

        # ---------------------------------------------------------
        # 1. SEEKER / TENANT REMINDER
        # ---------------------------------------------------------
        seeker_profile, _ = UserProfile.objects.get_or_create(
            user=seeker,
        )

        if getattr(seeker_profile, "notify_reminders", True):
            seeker_title = "Upcoming viewing"
            seeker_body = (
                f"Reminder: your viewing for '{room_title}' starts on "
                f"{start_str}. (booking_id={booking.id})"
            )

            seeker_in_app_exists = (
                Notification.objects
                .filter(
                    user=seeker,
                    type="booking_reminder",
                    body__icontains=f"(booking_id={booking.id})",
                )
                .filter(body__icontains=start_str)
                .exists()
            )

            if not seeker_in_app_exists:
                Notification.objects.create(
                    user=seeker,
                    type="booking_reminder",
                    title=seeker_title,
                    body=seeker_body,
                    audience=Notification.Audience.SEEKER,
                )

            if seeker_template:
                seeker_email_exists = (
                    OutboundNotification.objects.filter(
                        user=seeker,
                        template_key="booking.reminder",
                        channel=NotificationTemplate.CHANNEL_EMAIL,
                        context__booking_id=booking.id,
                        context__starts_at=start_str,
                    ).exists()
                )

                if not seeker_email_exists:
                    OutboundNotification.objects.create(
                        user=seeker,
                        channel=NotificationTemplate.CHANNEL_EMAIL,
                        template_key="booking.reminder",
                        scheduled_for=now,
                        context={
                            "user": {
                                "first_name": seeker.first_name,
                            },
                            "booking_id": booking.id,
                            "room_title": room_title,
                            "starts_at": start_str,
                            "cta_url": seeker_booking_url,
                        },
                    )

        # ---------------------------------------------------------
        # 2. LANDLORD REMINDER
        # ---------------------------------------------------------
        if landlord:
            landlord_profile, _ = UserProfile.objects.get_or_create(
                user=landlord,
            )

            if getattr(landlord_profile, "notify_reminders", True):
                landlord_title = "Upcoming property viewing"
                landlord_body = (
                    f"Reminder: {seeker_name} will be viewing your property "
                    f"'{room_title}' on {start_str}. "
                    f"(booking_id={booking.id})"
                )

                landlord_in_app_exists = (
                    Notification.objects
                    .filter(
                        user=landlord,
                        type="booking_reminder_landlord",
                        body__icontains=f"(booking_id={booking.id})",
                    )
                    .filter(body__icontains=start_str)
                    .exists()
                )

                if not landlord_in_app_exists:
                    Notification.objects.create(
                        user=landlord,
                        type="booking_reminder_landlord",
                        title=landlord_title,
                        body=landlord_body,
                        audience=Notification.Audience.LANDLORD,
                    )

                if landlord_template:
                    landlord_email_exists = (
                        OutboundNotification.objects.filter(
                            user=landlord,
                            template_key="booking.reminder_landlord",
                            channel=NotificationTemplate.CHANNEL_EMAIL,
                            context__booking_id=booking.id,
                            context__starts_at=start_str,
                        ).exists()
                    )

                    if not landlord_email_exists:
                        OutboundNotification.objects.create(
                            user=landlord,
                            channel=NotificationTemplate.CHANNEL_EMAIL,
                            template_key="booking.reminder_landlord",
                            scheduled_for=now,
                            context={
                                "user": {
                                    "first_name": landlord.first_name,
                                },
                                "booker": {
                                    "name": seeker_name,
                                },
                                "booking_id": booking.id,
                                "room_title": room_title,
                                "starts_at": start_str,
                                "cta_url": landlord_booking_url,
                            },
                        )

        # ---------------------------------------------------------
        # 3. ONE SHARED RENTCRIB MESSAGE / ENVELOPE REMINDER
        # ---------------------------------------------------------
        if landlord:
            event_key = (
                f"booking:{booking.id}:"
                f"{booking.start.isoformat()}:viewing_reminder"
            )

            existing_system_message = (
                Message.objects
                .filter(metadata__event_key=event_key)
                .first()
            )

            if existing_system_message is None:
                thread = get_or_create_canonical_thread(
                    landlord=landlord,
                    seeker=seeker,
                    room=room,
                )

                system_message = Message.objects.create(
                    thread=thread,

                    # A real sender is required by the model, but
                    # system_event=True marks this as RentCrib logic.
                    sender=landlord,

                    body=(
                        "Viewing reminder\n\n"
                        f"The viewing for {room_title} is scheduled for "
                        f"{start_str}.\n\n"
                        f"Viewer: {seeker_name}"
                    ),

                    message_type=Message.TYPE_TEXT,

                    metadata={
                        "system_event": True,
                        "event_type": "booking_reminder",
                        "event_key": event_key,
                        "booking_id": booking.id,
                        "room_id": room.id,
                        "room_title": room_title,
                        "starts_at": start_str,
                        "viewer_name": seeker_name,
                    },
                )

                # The shared inbox/envelope message exists for both parties,
                # regardless of their bell/email notification preferences.
                for user in (seeker, landlord):
                    if not user:
                        continue

                    push_user_realtime_event(
                        user.id,
                        "new_message",
                        {
                            "message_id": system_message.id,
                            "thread_id": thread.id,
                            "sender_id": system_message.sender_id,
                        },
                    )

                # Realtime bell update only where a bell notification
                # actually exists for that user.
                if getattr(seeker_profile, "notify_reminders", True):
                    push_user_realtime_event(
                        seeker.id,
                        "new_notification",
                        {
                            "kind": "booking_reminder",
                            "message_id": system_message.id,
                            "thread_id": thread.id,
                        },
                    )

                if (
                    landlord
                    and getattr(landlord_profile, "notify_reminders", True)
                ):
                    push_user_realtime_event(
                        landlord.id,
                        "new_notification",
                        {
                            "kind": "booking_reminder_landlord",
                            "message_id": system_message.id,
                            "thread_id": thread.id,
                        },
                    )

        processed += 1

    return processed