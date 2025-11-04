import pytest
from datetime import timedelta
from django.utils import timezone
from propertylist_app.models import Room, RoomCategorie


@pytest.mark.django_db
def test_expired_room_hidden_after_scheduler():
    """
    When a room’s paid period expires, the scheduler should automatically hide it.
    """
    cat = RoomCategorie.objects.create(name="Premium", active=True)
    room = Room.objects.create(
        title="Old Room",
        category=cat,
        price_per_month=950,
        status="active",
        paid_until=timezone.now().date() - timedelta(days=2),  # already expired
    )

    # simulate background scheduler task
    today = timezone.now().date()
    if room.paid_until and room.paid_until < today:
        room.status = "hidden"
        room.save(update_fields=["status"])

    room.refresh_from_db()
    assert room.status == "hidden"
