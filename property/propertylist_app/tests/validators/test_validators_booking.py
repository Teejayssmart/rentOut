import pytest
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth.models import User

from propertylist_app.models import Room, Booking
from propertylist_app.validators import validate_no_booking_conflict


@pytest.mark.django_db
def test_validate_no_booking_conflict():
    room = Room.objects.create(title="T", price_per_month=100, is_deleted=False)
    now = timezone.now()

    a_start, a_end = now + timedelta(days=1), now + timedelta(days=2)
    b_start, b_end = now + timedelta(days=3), now + timedelta(days=4)

    # Existing booking A
    user = User.objects.create_user(
        username="bkuser",
        password="pass12345",
        email="bkuser@test.com",
    )
    Booking.objects.create(room=room, user=user, start=a_start, end=a_end)

    # Overlapping should raise
    with pytest.raises(ValidationError):
        validate_no_booking_conflict(
            room,
            a_start + timedelta(hours=12),
            a_end,
            Booking.objects,
        )

    # Non-overlapping OK
    validate_no_booking_conflict(room, b_start, b_end, Booking.objects)
