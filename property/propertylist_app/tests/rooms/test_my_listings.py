import pytest
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie


User = get_user_model()


@pytest.fixture
def landlord(db):
    return User.objects.create_user(
        username="landlord1",
        password="testpass123",
        email="landlord1@example.com",
    )


@pytest.fixture
def other_landlord(db):
    return User.objects.create_user(
        username="landlord2",
        password="testpass123",
        email="landlord2@example.com",
    )


@pytest.fixture
def default_category(db):
    cat, _ = RoomCategorie.objects.get_or_create(
        name="General",
        defaults={"key": "general", "slug": "general", "active": True},
    )
    return cat


@pytest.fixture
def auth_client(landlord):
    client = APIClient()
    client.force_authenticate(user=landlord)
    return client


def _make_room(owner, title, paid_until, *, category, status="active"):
    room = Room(
        title=title,
        description="Nice room",
        price_per_month=Decimal("500.00"),
        location="SW1A 1AA",
        category=category,
        property_owner=owner,
        property_type="flat",
        available_from=date.today() + timedelta(days=1),
        paid_until=paid_until,
        status=status,
    )
    room.save()
    return room


@pytest.mark.django_db
def test_my_listings_filters_by_state(auth_client, landlord, other_landlord, default_category):
    today = date.today()

    _make_room(
        landlord,
        "Draft Room",
        paid_until=None,
        category=default_category,
    )

    _make_room(
        landlord,
        "Active Room",
        paid_until=today + timedelta(days=7),
        category=default_category,
    )

    _make_room(
        landlord,
        "Expired Room",
        paid_until=today - timedelta(days=1),
        category=default_category,
    )

    _make_room(
        landlord,
        "Hidden Room",
        paid_until=today + timedelta(days=7),
        category=default_category,
        status="hidden",
    )

    _make_room(
        other_landlord,
        "Other Landlord Room",
        paid_until=today + timedelta(days=7),
        category=default_category,
    )

    url = reverse("api:my-listings")

    resp = auth_client.get(url, {"state": "draft"})
    assert resp.status_code == 200
    titles = {r["title"] for r in resp.data}
    states = {r["listing_state"] for r in resp.data}
    assert titles == {"Draft Room"}
    assert states == {"draft"}

    resp = auth_client.get(url, {"state": "active"})
    assert resp.status_code == 200
    titles = {r["title"] for r in resp.data}
    states = {r["listing_state"] for r in resp.data}
    assert titles == {"Active Room"}
    assert states == {"active"}

    resp = auth_client.get(url, {"state": "expired"})
    assert resp.status_code == 200
    titles = {r["title"] for r in resp.data}
    states = {r["listing_state"] for r in resp.data}
    assert titles == {"Expired Room"}
    assert states == {"expired"}

    resp = auth_client.get(url, {"state": "hidden"})
    assert resp.status_code == 200
    titles = {r["title"] for r in resp.data}
    states = {r["listing_state"] for r in resp.data}
    assert titles == {"Hidden Room"}
    assert states == {"hidden"}

    resp = auth_client.get(url)
    assert resp.status_code == 200
    titles = {r["title"] for r in resp.data}
    assert "Other Landlord Room" not in titles
    assert {"Draft Room", "Active Room", "Expired Room", "Hidden Room"}.issubset(titles)