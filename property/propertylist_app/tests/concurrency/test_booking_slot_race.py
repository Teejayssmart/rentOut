import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import AvailabilitySlot, Booking

pytestmark = pytest.mark.django_db


def _post_slot_booking(user, slot_id, results, errors, barrier=None):
    try:
        c = APIClient()
        c.force_authenticate(user=user)
        if barrier is not None:
            barrier.wait(timeout=5)
        res = c.post("/api/bookings/", data={"slot": slot_id}, format="json")
        results.append((res.status_code, getattr(res, "data", None)))
    except Exception as e:
        errors.append(repr(e))


def test_two_users_cannot_overbook_same_slot(user_factory, room_factory):
    """
    Concurrency/race condition protection for slot bookings.

    - For SQLite: run a deterministic sequential test (SQLite doesn't enforce row locks like Postgres/MySQL).
    - For Postgres/MySQL: run a true parallel attempt and assert only one booking succeeds.

    Expected invariant (all DBs):
    - active bookings for the slot never exceed max_bookings.
    """
    landlord = user_factory(username="owner1", role="landlord")
    room = room_factory(property_owner=landlord)

    tenant1 = user_factory(username="tenant1", role="seeker")
    tenant2 = user_factory(username="tenant2", role="seeker")

    now = timezone.now()
    slot = AvailabilitySlot.objects.create(
        room=room,
        start=now + timedelta(hours=2),
        end=now + timedelta(hours=3),
        max_bookings=1,
    )

    # -----------------------------
    # SQLite fallback: deterministic (still validates your "fully booked" rule)
    # -----------------------------
    if connection.vendor == "sqlite":
        c1 = APIClient()
        c1.force_authenticate(user=tenant1)
        r1 = c1.post("/api/bookings/", data={"slot": slot.id}, format="json")
        assert r1.status_code in (200, 201), getattr(r1, "data", None)

        c2 = APIClient()
        c2.force_authenticate(user=tenant2)
        r2 = c2.post("/api/bookings/", data={"slot": slot.id}, format="json")
        assert r2.status_code == 400, getattr(r2, "data", None)

        active = Booking.objects.filter(slot=slot, canceled_at__isnull=True).count()
        assert active == 1
        return

    # -----------------------------
    # Postgres/MySQL: true parallel race attempt
    # -----------------------------
    barrier = threading.Barrier(2)
    results = []
    errors = []

    t1 = threading.Thread(target=_post_slot_booking, args=(tenant1, slot.id, results, errors, barrier))
    t2 = threading.Thread(target=_post_slot_booking, args=(tenant2, slot.id, results, errors, barrier))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Thread errors occurred: {errors}"
    assert len(results) == 2, results

    # one success, one rejected
    status_codes = [s for (s, _) in results]
    assert any(code in (200, 201) for code in status_codes), results
    assert any(code == 400 for code in status_codes), results

    active = Booking.objects.filter(slot=slot, canceled_at__isnull=True).count()
    assert active == 1
