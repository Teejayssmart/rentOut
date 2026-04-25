import pytest
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth.models import User

from propertylist_app.models import Room, RoomCategorie, Booking
from propertylist_app.validators import validate_no_booking_conflict


@pytest.mark.django_db
def test_validate_no_booking_conflict():
    owner = User.objects.create_user(
        username="room_owner",
        password="pass12345",
        email="room_owner@test.com",
    )
    category = RoomCategorie.objects.create(name="Validator Category", active=True)

    room = Room.objects.create(
        title="T",
        description="Validator test room",
        price_per_month=100,
        location="SO14",
        category=category,
        property_owner=owner,
        is_deleted=False,
    )

    now = timezone.now()

    a_start, a_end = now + timedelta(days=1), now + timedelta(days=2)
    b_start, b_end = now + timedelta(days=3), now + timedelta(days=4)

    user = User.objects.create_user(
        username="bkuser",
        password="pass12345",
        email="bkuser@test.com",
    )
    Booking.objects.create(room=room, user=user, start=a_start, end=a_end)

    with pytest.raises(ValidationError):
        validate_no_booking_conflict(
            room,
            a_start + timedelta(hours=12),
            a_end,
            Booking.objects,
        )

    validate_no_booking_conflict(room, b_start, b_end, Booking.objects)