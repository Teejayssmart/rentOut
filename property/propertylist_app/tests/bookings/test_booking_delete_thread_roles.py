import pytest

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import (
    Room,
    RoomCategorie,
    Booking,
    MessageThread,
)


User = get_user_model()


@pytest.mark.django_db
def test_booking_delete_snapshots_thread_roles():
    landlord = User.objects.create_user(
        username="delete-landlord",
        email="delete-landlord@test.com",
        password="pass12345",
    )
    seeker = User.objects.create_user(
        username="delete-seeker",
        email="delete-seeker@test.com",
        password="pass12345",
    )

    category = RoomCategorie.objects.create(
        name="General",
        active=True,
    )

    room = Room.objects.create(
        title="Delete Test Room",
        category=category,
        property_owner=landlord,
        price_per_month=500,
    )

    start = timezone.now() + timedelta(days=2)
    end = start + timedelta(hours=1)

    booking = Booking.objects.create(
        room=room,
        user=seeker,
        start=start,
        end=end,
        status=Booking.STATUS_ACTIVE,
    )

    client = APIClient()
    client.force_authenticate(seeker)

    response = client.delete(
        f"/api/v1/bookings/{booking.id}/delete/"
    )

    assert response.status_code == 200

    thread = (
        MessageThread.objects
        .filter(room=room)
        .filter(participants=landlord)
        .filter(participants=seeker)
        .distinct()
        .get()
    )

    assert thread.landlord_id == landlord.id
    assert thread.seeker_id == seeker.id