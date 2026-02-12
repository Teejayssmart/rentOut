import pytest
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User

from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, AvailabilitySlot, Booking


@pytest.mark.django_db
def test_direct_booking_conflict_and_boundaries():
    """
    Covers:
      - happy path: create a booking (201)
      - overlap rejected: second booking overlaps -> 400 {"detail": ...}
      - boundary allowed: new.start == existing.end -> allowed (201)
      - invalid range: end <= start -> 400 {"end": "..."}
    """
    u = User.objects.create_user(username="u1", password="pass12345", email="u1@example.com")

    cat = RoomCategorie.objects.create(name="Central", active=True)
    room = Room.objects.create(
        title="Cozy Room",
        category=cat,
        price_per_month=900,
        property_owner=u,
    )

    client = APIClient()
    client.force_authenticate(user=u)

    url = reverse("v1:bookings-list-create")

    base = timezone.now() + timedelta(days=2)
    start_1 = base.replace(microsecond=0)
    end_1 = (base + timedelta(hours=2)).replace(microsecond=0)

    # 1) happy path
    r1 = client.post(
        url,
        {"room": room.id, "start": start_1.isoformat(), "end": end_1.isoformat()},
        format="json",
    )
    assert r1.status_code == 201, r1.data
    assert Booking.objects.filter(room=room).count() == 1

    # 2) overlap rejected
    overlap_start = (start_1 + timedelta(minutes=30)).isoformat()
    overlap_end = (end_1 + timedelta(hours=1)).isoformat()
    r2 = client.post(url, {"room": room.id, "start": overlap_start, "end": overlap_end}, format="json")
    assert r2.status_code == 400
    assert "detail" in r2.data

    # 3) boundary allowed
    boundary_start = end_1.isoformat()
    boundary_end = (end_1 + timedelta(hours=2)).isoformat()
    r3 = client.post(url, {"room": room.id, "start": boundary_start, "end": boundary_end}, format="json")
    assert r3.status_code == 201, r3.data
    assert Booking.objects.filter(room=room).count() == 2

    # 4) invalid range (end <= start)
    bad_start = (base + timedelta(days=1)).isoformat()
    bad_end = (base + timedelta(days=1)).isoformat()
    r4 = client.post(url, {"room": room.id, "start": bad_start, "end": bad_end}, format="json")
    assert r4.status_code == 400, r4.data

    err = r4.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "end" in err.get("field_errors", {}), f"Expected 'end' error, got {err}"

    
    # reason: A4 envelope stores field-level errors inside field_errors
    end_val = err.get("field_errors", {}).get("end")
    assert end_val is not None, f"Expected end error list, got {err}"
    assert any("End must be after start" in str(x) for x in end_val), f"Unexpected end error: {end_val}"


@pytest.mark.django_db
def test_slot_booking_capacity_and_past_slot():
    """
    Covers:
      - booking a slot (max_bookings=1) succeeds once -> 201
      - second booking on same slot blocked -> 400 {"detail": "This slot is fully booked."}
      - booking a past slot -> 400 {"slot": "This slot is in the past."}
    """
    owner = User.objects.create_user(username="owner", password="pass12345", email="o@example.com")
    guest1 = User.objects.create_user(username="guest1", password="pass12345", email="g1@example.com")
    guest2 = User.objects.create_user(username="guest2", password="pass12345", email="g2@example.com")

    cat = RoomCategorie.objects.create(name="Suburbs", active=True)
    room = Room.objects.create(
        title="Room with Slots",
        category=cat,
        price_per_month=800,
        property_owner=owner,
    )

    # Future slot
    start = (timezone.now() + timedelta(days=3)).replace(microsecond=0)
    end = (start + timedelta(hours=2)).replace(microsecond=0)
    slot = AvailabilitySlot.objects.create(room=room, start=start, end=end, max_bookings=1)

    url = reverse("v1:bookings-list-create")

    # guest1 books -> OK
    c1 = APIClient()
    c1.force_authenticate(user=guest1)
    r1 = c1.post(url, {"slot": slot.id}, format="json")
    assert r1.status_code == 201, r1.data
    assert Booking.objects.filter(slot=slot, canceled_at__isnull=True).count() == 1

    # guest2 tries same slot -> full
    c2 = APIClient()
    c2.force_authenticate(user=guest2)
    r2 = c2.post(url, {"slot": slot.id}, format="json")
    assert r2.status_code == 400, r2.data
    assert "detail" in r2.data

    # Past slot -> rejected
    past_start = (timezone.now() - timedelta(days=2)).replace(microsecond=0)
    past_end = (past_start + timedelta(hours=1)).replace(microsecond=0)
    past_slot = AvailabilitySlot.objects.create(room=room, start=past_start, end=past_end, max_bookings=1)

    r3 = c2.post(url, {"slot": past_slot.id}, format="json")
    assert r3.status_code == 400, r3.data

    err = r3.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "slot" in err.get("field_errors", {}), f"Expected 'slot' error, got {err}"

    # reason: A4 envelope stores field-level errors inside field_errors
    slot_val = err.get("field_errors", {}).get("slot")
    assert slot_val is not None, f"Expected slot error list, got {err}"
    assert any("past" in str(x).lower() for x in slot_val), f"Unexpected slot error: {slot_val}"




