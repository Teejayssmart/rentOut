import threading
from datetime import timedelta
from queue import Queue

import pytest
from django.db import connection, connections
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import AvailabilitySlot, Booking


# Reason: API is versioned; using /api/v1 avoids 308 redirects from /api -> /api/v1
BOOKINGS_URL = "/api/v1/bookings/"


def _post_slot_booking(user, slot_id, results: Queue, errors: Queue, barrier: threading.Barrier):
    """
    Thread helper: performs a single booking POST and records exactly one result.
    Always closes DB connections for this thread (important for Postgres test DB teardown).
    """
    try:
        barrier.wait(timeout=5)
        c = APIClient()
        c.force_authenticate(user=user)
        res = c.post(BOOKINGS_URL, data={"slot": slot_id}, format="json")
        results.put((res.status_code, getattr(res, "data", None)))
    except Exception as e:
        errors.put(repr(e))
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_two_users_cannot_overbook_same_slot(user_factory, room_factory):
    """
    Concurrency/race condition protection for slot bookings.

    - For SQLite: deterministic sequential test (SQLite doesn't enforce row locks like Postgres/MySQL).
    - For Postgres/MySQL: true parallel attempt and assert only one booking succeeds.

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
        r1 = c1.post(BOOKINGS_URL, data={"slot": slot.id}, format="json")
        assert r1.status_code in (200, 201), getattr(r1, "data", None)

        c2 = APIClient()
        c2.force_authenticate(user=tenant2)
        r2 = c2.post(BOOKINGS_URL, data={"slot": slot.id}, format="json")
        assert r2.status_code == 400, getattr(r2, "data", None)

        active = Booking.objects.filter(slot=slot, canceled_at__isnull=True).count()
        assert active == 1
        return

    # -----------------------------
    # Postgres/MySQL: true parallel race attempt
    # -----------------------------
    barrier = threading.Barrier(2)
    results = Queue()
    errors = Queue()

    t1 = threading.Thread(target=_post_slot_booking, args=(tenant1, slot.id, results, errors, barrier))
    t2 = threading.Thread(target=_post_slot_booking, args=(tenant2, slot.id, results, errors, barrier))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors.empty(), f"Thread errors occurred: {[errors.get() for _ in range(errors.qsize())]}"

    collected = [results.get() for _ in range(results.qsize())]
    assert len(collected) == 2, collected

    status_codes = [s for (s, _) in collected]
    assert any(code in (200, 201) for code in status_codes), collected
    assert any(code == 400 for code in status_codes), collected

    active = Booking.objects.filter(slot=slot, canceled_at__isnull=True).count()
    assert active == 1