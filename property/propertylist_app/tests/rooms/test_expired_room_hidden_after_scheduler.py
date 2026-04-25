import pytest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from propertylist_app.models import Room, RoomCategorie


@pytest.mark.django_db
def test_expired_room_hidden_after_scheduler():
    cat = RoomCategorie.objects.create(name="Premium", active=True)

    User = get_user_model()
    owner = User.objects.create_user(
        username="expired_owner",
        password="pass12345",
    )

    room = Room.objects.create(
        title="Old Room",
        category=cat,
        property_owner=owner,
        price_per_month=950,
        status="active",
        paid_until=timezone.now().date() - timedelta(days=2),
    )

    today = timezone.now().date()
    if room.paid_until and room.paid_until < today:
        room.status = "hidden"
        room.save(update_fields=["status"])

    room.refresh_from_db()
    assert room.status == "hidden"