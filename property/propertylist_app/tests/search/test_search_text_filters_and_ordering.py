import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie

User = get_user_model()


@pytest.mark.django_db
def test_text_and_price_filters():
    """
    /api/search/rooms/?q=&min_price=&max_price=
    Ensures text search and price range both filter results.
    """
    owner = User.objects.create_user(username="owner", password="pass123")
    cat = RoomCategorie.objects.create(name="General", active=True)

    Room.objects.create(
        title="Cozy flat in London",
        description="Nice and clean near station",
        price_per_month=900,
        location="London SW1A 1AA",
        category=cat,
        property_owner=owner,
    )
    Room.objects.create(
        title="Luxury apartment",
        description="Spacious apartment in Birmingham",
        price_per_month=2000,
        location="Birmingham B1 1AA",
        category=cat,
        property_owner=owner,
    )
    
    test_requires_postcode_when_radius_provided

    client = APIClient()
    url = reverse("v1:search-rooms")

    # Text filter
    r1 = client.get(url, {"q": "cozy"})
    assert r1.status_code == 200
    titles1 = [it["title"].lower() for it in r1.json().get("results", r1.json())]
    assert any("cozy" in t for t in titles1)

    # Price range filter
    r2 = client.get(url, {"min_price": 1000, "max_price": 3000})
    assert r2.status_code == 200
    items2 = r2.json().get("results", r2.json())
    assert all(1000 <= float(it["price_per_month"]) <= 3000 for it in items2)


@pytest.mark.django_db
def test_ordering_by_created_and_price():
    """
    /api/search/rooms/?ordering=created_at | -created_at | price_per_month | -price_per_month
    """
    owner = User.objects.create_user(username="o2", password="pass123")
    cat = RoomCategorie.objects.create(name="Cat", active=True)

    r1 = Room.objects.create(
        title="A",
        description="..",
        price_per_month=500,
        location="London",
        category=cat,
        property_owner=owner,
    )
    r2 = Room.objects.create(
        title="B",
        description="..",
        price_per_month=800,
        location="London",
        category=cat,
        property_owner=owner,
    )

    client = APIClient()
    url = reverse("v1:search-rooms")

    # created_at descending: latest first (r2 after r1)
    rd = client.get(url, {"ordering": "-created_at"})
    assert rd.status_code == 200
    titles_desc = [it["title"] for it in rd.json().get("results", rd.json())]
    assert titles_desc.index("B") < titles_desc.index("A")

    # price ascending: cheaper first
    rp = client.get(url, {"ordering": "price_per_month"})
    assert rp.status_code == 200
    prices = [float(it["price_per_month"]) for it in rp.json().get("results", rp.json())]
    assert prices == sorted(prices)


@pytest.mark.django_db
def test_requires_postcode_when_radius_provided():
    """
    /api/search/rooms/?radius_miles=... must include postcode
    """
    owner = User.objects.create_user(username="o3", password="pass123")
    cat = RoomCategorie.objects.create(name="X", active=True)
    Room.objects.create(
        title="Room",
        description="..",
        price_per_month=700,
        location="Manchester M1 1AA",
        category=cat,
        property_owner=owner,
    )

    client = APIClient()
    url = reverse("v1:search-rooms")
    r = client.get(url, {"radius_miles": 10})
    assert r.status_code == 400
    body = r.json()

    assert body.get("ok") is False
    assert body.get("code") == "validation_error"
    assert "postcode" in body.get("field_errors", {})



@pytest.mark.django_db
def test_pagination_limit_works():
    """
    Basic sanity: limit controls number of items in page.
    """
    owner = User.objects.create_user(username="o4", password="pass123")
    cat = RoomCategorie.objects.create(name="Pag", active=True)
    for i in range(6):
        Room.objects.create(
            title=f"R{i}",
            description="..",
            price_per_month=600 + i,
            location="Leeds LS1 1AA",
            category=cat,
            property_owner=owner,
        )

    client = APIClient()
    url = reverse("v1:search-rooms")

    r = client.get(url, {"limit": 2})
    assert r.status_code == 200
    data = r.json()
    # RoomLOPagination returns {"count", "next", "previous", "results"}
    results = data.get("results", data)
    assert len(results) == 2
