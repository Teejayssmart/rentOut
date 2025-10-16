import pytest
from datetime import date
from decimal import Decimal
from django.contrib.auth.models import User
from django.urls import reverse
from propertylist_app.models import Room, RoomCategorie

pytestmark = pytest.mark.django_db  # this file hits the DB

# --- helpers (minimal “factory” style) ---------------------------------------
def make_user(i=1):
    return User.objects.create_user(
        username=f"user{i}",
        email=f"u{i}@ex.com",
        password="pass12345",
    )

def make_category(name="Central", active=True):
    return RoomCategorie.objects.create(name=name, active=active)

def make_room(
    *,
    owner=None,
    cat=None,
    title="Room A",
    price=750,
    avg_rating=0.0,
):
    """Create a minimal valid Room that satisfies NOT NULL fields."""
    owner = owner or make_user()
    cat = cat or make_category()
    return Room.objects.create(
        title=title,
        description="",
        price_per_month=Decimal(price),
        location="",
        category=cat,
        available_from=date.today(),
        is_available=True,
        furnished=False,
        bills_included=False,
        property_owner=owner,
        image=None,
        number_of_bedrooms=1,
        number_of_bathrooms=1,
        property_type="flat",
        parking_available=False,
        avg_rating=avg_rating,
        number_rating=0,
        status="active",
    )

# --- test A: ordering by rating desc -----------------------------------------
def test_rooms_alt_order_by_avg_rating_desc(client):
    # data setup
    owner = make_user()
    cat_central = make_category("Central")
    cat_suburbs = make_category("Suburbs")

    r1 = make_room(owner=owner, cat=cat_suburbs, title="Room 1", price=900, avg_rating=4.2)
    r2 = make_room(owner=owner, cat=cat_central, title="Room 2", price=1200, avg_rating=4.9)
    r3 = make_room(owner=owner, cat=cat_central, title="Room 3", price=800, avg_rating=3.5)

    # call the endpoint with ordering
    url = reverse("v1:room-list-alt") + "?ordering=-avg_rating"
    resp = client.get(url)

    # assertions
    assert resp.status_code == 200
    titles = [item["title"] for item in resp.data["results"]]
    assert titles[:3] == ["Room 2", "Room 1", "Room 3"]


def test_rooms_alt_pagination_limit_offset(client):
    owner = make_user()
    cat = make_category("Central")

    for i in range(7):
        make_room(owner=owner, cat=cat, title=f"R{i}", price=500 + i, avg_rating=4.0)

    url = reverse("v1:room-list-alt") + "?limit=3&offset=3"
    resp = client.get(url)

    assert resp.status_code == 200
    assert resp.data["count"] >= 7
    assert len(resp.data["results"]) == 3
