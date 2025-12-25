import pytest
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from propertylist_app.models import Notification, UserProfile, Room


pytestmark = pytest.mark.django_db


def test_booking_create_creates_confirmation_notification_when_enabled(user_factory, room_factory):
    client = APIClient()
    user = user_factory()
    client.force_authenticate(user=user)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_confirmations = True
    profile.save(update_fields=["notify_confirmations"])

    room = room_factory()

    payload = {
        "room": room.id,
        "start": timezone.now() + timedelta(days=5),
        "end": timezone.now() + timedelta(days=7),
    }

    res = client.post("/api/bookings/", payload, format="json")
    assert res.status_code in [200, 201], res.data

    assert Notification.objects.filter(
        user=user,
        type="confirmation",
        title="Booking confirmed",
    ).exists()


def test_booking_create_does_not_create_confirmation_notification_when_disabled(user_factory, room_factory):
    client = APIClient()
    user = user_factory()
    client.force_authenticate(user=user)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_confirmations = False
    profile.save(update_fields=["notify_confirmations"])

    room = room_factory()

    payload = {
        "room": room.id,
        "start": timezone.now() + timedelta(days=5),
        "end": timezone.now() + timedelta(days=7),
    }

    res = client.post("/api/bookings/", payload, format="json")
    assert res.status_code in [200, 201], res.data

    assert not Notification.objects.filter(
        user=user,
        type="confirmation",
        title="Booking confirmed",
    ).exists()
