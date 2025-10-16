import pytest
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User

from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, Booking


@pytest.mark.django_db
def test_bookings_default_ordering_newest_first():
    # users
    u1 = User.objects.create_user(username="alice", email="a@x.com", password="pass12345")

    # minimal category + room that satisfies your Room model requirements
    cat = RoomCategorie.objects.create(name="Central", active=True)
    room = Room.objects.create(
        title="Room A",
        description="",
        price_per_month=Decimal("750"),
        location="",
        category=cat,
        property_owner=u1,
        number_of_bedrooms=1,
        number_of_bathrooms=1,
        property_type="flat",
        avg_rating=4.0,  # optional but handy for realism
    )

    # create two bookings at different times so created_at differs
    now = timezone.now()
    b1 = Booking.objects.create(user=u1, room=room, start=now + timedelta(days=1), end=now + timedelta(days=2))
    b2 = Booking.objects.create(user=u1, room=room, start=now + timedelta(days=3), end=now + timedelta(days=4))

    # authenticate + call API
    client = APIClient()
    client.force_authenticate(user=u1)

    url = reverse("v1:bookings-list-create")  # /api/v1/bookings/
    r = client.get(url)

    assert r.status_code == 200
    # default ordering should be newest first (b2 before b1)
    ids = [row["id"] for row in r.data["results"]] if isinstance(r.data, dict) and "results" in r.data else [row["id"] for row in r.data]
    assert ids[:2] == [b2.id, b1.id]


@pytest.mark.django_db
def test_bookings_order_by_start_asc():
    # users
    u1 = User.objects.create_user(username="alice", email="a@x.com", password="pass12345")

    # minimal category + room
    cat = RoomCategorie.objects.create(name="Central", active=True)
    room = Room.objects.create(
        title="Room A",
        description="",
        price_per_month=Decimal("750"),
        location="",
        category=cat,
        property_owner=u1,
        number_of_bedrooms=1,
        number_of_bathrooms=1,
        property_type="flat",
        avg_rating=4.0,
    )

    # create three bookings out of chronological order
    now = timezone.now()
    b_mid = Booking.objects.create(user=u1, room=room, start=now + timedelta(days=3), end=now + timedelta(days=4))
    b_early = Booking.objects.create(user=u1, room=room, start=now + timedelta(days=1), end=now + timedelta(days=2))
    b_late = Booking.objects.create(user=u1, room=room, start=now + timedelta(days=5), end=now + timedelta(days=6))

    # authenticate + call API with ordering query
    client = APIClient()
    client.force_authenticate(user=u1)

    url = reverse("v1:bookings-list-create")  # /api/v1/bookings/
    r = client.get(url + "?ordering=start")

    assert r.status_code == 200
    ids = [row["id"] for row in r.data["results"]] if isinstance(r.data, dict) and "results" in r.data else [row["id"] for row in r.data]
    # ascending by start: early, mid, late
    assert ids[:3] == [b_early.id, b_mid.id, b_late.id]
