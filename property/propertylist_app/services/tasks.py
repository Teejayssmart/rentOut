from __future__ import annotations
from datetime import date
from typing import Optional

from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from propertylist_app.models import Room, Message, MessageThread, Notification


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
