import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from datetime import timedelta

from propertylist_app.models import Room, SavedRoom, AvailabilitySlot, Review, Tenancy

pytestmark = pytest.mark.django_db


def test_room_title_unique_case_insensitive_for_alive_rooms(user_factory, room_factory):
    """
    DB constraint: Room title is unique case-insensitively for alive (is_deleted=False) rooms.
    Also proves soft-delete releases the constraint so the same title can be reused.
    """
    landlord = user_factory(username="db_landlord1", role="landlord")

    r1 = room_factory(property_owner=landlord, title="Nice Double Room")
    assert r1.is_deleted is False

    # Same title but different case must fail while first room is alive.
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            room_factory(property_owner=landlord, title="nice double room")

    # Soft-delete the first room -> constraint condition no longer applies
    r1.soft_delete()
    r1.refresh_from_db()
    assert r1.is_deleted is True

    # Now the reused title should succeed
    r2 = room_factory(property_owner=landlord, title="nice double room")
    assert r2.id is not None


def test_savedroom_unique_together_user_room(user_factory, room_factory):
    """
    DB constraint: SavedRoom unique_together(user, room) prevents duplicate saves.
    """
    landlord = user_factory(username="db_landlord2", role="landlord")
    tenant = user_factory(username="db_tenant2", role="seeker")
    room = room_factory(property_owner=landlord)

    SavedRoom.objects.create(user=tenant, room=room)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SavedRoom.objects.create(user=tenant, room=room)


def test_availabilityslot_check_constraints_enforced(user_factory, room_factory):
    """
    DB constraints:
    - end must be > start
    - max_bookings must be >= 1
    """
    landlord = user_factory(username="db_landlord3", role="landlord")
    room = room_factory(property_owner=landlord)

    start = timezone.now() + timedelta(days=1)
    end = start - timedelta(hours=1)

    # end <= start violates slot_end_after_start
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AvailabilitySlot.objects.create(room=room, start=start, end=end, max_bookings=1)

    # max_bookings < 1 violates slot_max_bookings_gte_1
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AvailabilitySlot.objects.create(
                room=room,
                start=start,
                end=start + timedelta(hours=1),
                max_bookings=0,
            )


def test_review_unique_once_per_tenancy_role(user_factory, room_factory):
    """
    DB constraint: only one review per (tenancy, role).
    """
    landlord = user_factory(username="db_landlord4", role="landlord")
    tenant = user_factory(username="db_tenant4", role="seeker")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        status=getattr(Tenancy, "STATUS_ENDED", "ended"),
        move_in_date=timezone.localdate() - timedelta(days=30),
        duration_months=6,
        review_open_at=now - timedelta(days=1),
        review_deadline_at=now + timedelta(days=10),
    )

    Review.objects.create(
        tenancy=tenancy,
        role=Review.ROLE_TENANT_TO_LANDLORD,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Review.objects.create(
                tenancy=tenancy,
                role=Review.ROLE_TENANT_TO_LANDLORD,
            )
