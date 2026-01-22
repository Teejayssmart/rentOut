import pytest
from django.utils import timezone
from datetime import timedelta

from propertylist_app.models import SavedRoom, AvailabilitySlot, Booking

pytestmark = pytest.mark.django_db


def test_soft_delete_room_does_not_cascade(user_factory, room_factory):
    """
    Soft-delete should NOT remove related rows (SavedRoom etc).
    It only marks the Room as is_deleted=True.
    """
    landlord = user_factory(username="del_landlord1", role="landlord")
    tenant = user_factory(username="del_tenant1", role="seeker")
    room = room_factory(property_owner=landlord)

    saved = SavedRoom.objects.create(user=tenant, room=room)

    room.soft_delete()
    room.refresh_from_db()

    assert room.is_deleted is True
    # related rows still exist (because we didn't hard delete)
    assert SavedRoom.objects.filter(id=saved.id).exists()


import pytest
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from datetime import timedelta

from propertylist_app.models import SavedRoom, AvailabilitySlot, Booking

pytestmark = pytest.mark.django_db


def test_hard_delete_room_is_protected_when_related_history_exists(user_factory, room_factory):
    """
    DB behaviour: Room hard-delete is PROTECTED when related history exists
    (e.g., AvailabilitySlot/Booking). This forces the app to use soft-delete.
    """
    landlord = user_factory(username="del_landlord2", role="landlord")
    tenant = user_factory(username="del_tenant2", role="seeker")
    room = room_factory(property_owner=landlord)

    SavedRoom.objects.create(user=tenant, room=room)

    start = timezone.now() + timedelta(days=2)
    end = start + timedelta(hours=1)
    slot = AvailabilitySlot.objects.create(room=room, start=start, end=end, max_bookings=1)

    Booking.objects.create(user=tenant, room=room, slot=slot, start=start, end=end)

    with pytest.raises(ProtectedError):
        room.delete()
