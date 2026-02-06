import pytest
from unittest.mock import patch
from django.contrib.auth import get_user_model
from propertylist_app.models import MessageThread, Message, Room, RoomCategorie, Notification as InAppNotification
from notifications.models import NotificationTemplate, OutboundNotification
from django.utils import timezone
from datetime import timedelta

pytestmark = pytest.mark.django_db

def make_users(n=2):
    U = get_user_model()
    return [U.objects.create_user(username=f"u{i}", email=f"u{i}@ex.com", password="x", first_name=f"U{i}") for i in range(n)]

def test_new_message_signal_queues_emails_and_inapp():
    sender, recipient = make_users(2)
    t = MessageThread.objects.create()
    t.participants.add(sender, recipient)

    # Email template for message.new
    NotificationTemplate.objects.create(
        key="message.new", channel="email", subject="New from {{ sender.name }}", body="Hi {{ user.first_name }}", is_active=True
    )

    # Avoid actually sending emails when the task runs later
    with patch("notifications.services.send_mail", return_value=1):
        msg = Message.objects.create(thread=t, sender=sender, body="Hello there")

    # Outbound for recipient (not sender)
    queued = OutboundNotification.objects.filter(template_key="message.new", user=recipient)
    assert queued.count() == 1

    # In-app notification created
    assert InAppNotification.objects.filter(user=recipient, thread=t, message=msg).exists()

def test_new_booking_signal_queues_owner_and_booker_emails():
    owner, booker = make_users(2)
    cat = RoomCategorie.objects.create(name="General", key="general", slug="general", active=True)
    room = Room.objects.create(
        title="Room A", description="d", price_per_month=500, location="SO14", category=cat,
        property_owner=owner, property_type="flat"
    )

    for key in ("booking.new", "booking.confirmation"):
        NotificationTemplate.objects.create(key=key, channel="email", subject="S", body="B", is_active=True)

    from propertylist_app.models import Booking
    with patch("notifications.services.send_mail", return_value=1):
            start = timezone.now()
            end = start + timedelta(hours=1)

            Booking.objects.create(
                user=booker,
                room=room,
                start=start,
                end=end,
            )

    assert OutboundNotification.objects.filter(template_key="booking.new", user=owner).exists()
    assert OutboundNotification.objects.filter(template_key="booking.confirmation", user=booker).exists()
