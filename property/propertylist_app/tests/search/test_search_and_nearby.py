import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie


@pytest.mark.django_db
def test_nearby_orders_by_distance_and_attaches_distance(monkeypatch):
    """
    GET /api/rooms/nearby/?postcode=...&radius_miles=...
    - Sorted by distance ascending
    - Each item has distance_miles
    """
    # Patch the symbol used inside the views module
    def fake_geocode(_postcode):
        return (51.5074, -0.1278)  # London
    monkeypatch.setattr("propertylist_app.api.views.geocode_postcode_cached", fake_geocode)

    owner = User.objects.create_user(username="o", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Any", active=True)

    # Three rooms around London with increasing distance
    Room.objects.create(title="Near", category=cat, price_per_month=800, property_owner=owner,
                        latitude=51.51, longitude=-0.10)
    Room.objects.create(title="Mid", category=cat, price_per_month=850, property_owner=owner,
                        latitude=51.60, longitude=-0.20)
    Room.objects.create(title="Far", category=cat, price_per_month=900, property_owner=owner,
                        latitude=52.00, longitude=0.00)

    client = APIClient()
    url = reverse("v1:rooms-nearby")
    r = client.get(url, {"postcode": "SW1A 1AA", "radius_miles": 200})
    assert r.status_code == 200, r.data

    # ... keep everything above as-is ...

    client = APIClient()
    url = reverse("v1:rooms-nearby")
    r = client.get(url, {"postcode": "SW1A 1AA", "radius_miles": 200})
    assert r.status_code == 200, r.data

    #  Support Option A: {"ok": true, "data": ...}
    payload = r.data
    if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
        payload = payload["data"]

    #  Support both paginated dict {"results": [...]} and plain list [...]
    results = payload.get("results", payload) if isinstance(payload, dict) else payload

    titles = [it["title"] for it in results[:3]]
    assert titles == ["Near", "Mid", "Far"]

    # Each item must include distance_miles
    for it in results[:3]:
        assert it.get("distance_miles") is not None

    assert titles == ["Near", "Mid", "Far"]

    dists = [it.get("distance_miles") for it in results[:3]]
    assert all(isinstance(d, (int, float)) for d in dists)
    assert dists[0] <= dists[1] <= dists[2]


@pytest.mark.django_db
def test_search_with_postcode_distance_ordering_and_reverse(monkeypatch):
    """
    GET /api/search/rooms/?postcode=...&ordering=distance_miles|-distance_miles
    - Respects distance ordering both directions
    """
    def fake_geocode(_postcode):
        return (51.5074, -0.1278)  # London
    monkeypatch.setattr("propertylist_app.api.views.geocode_postcode_cached", fake_geocode)
    
    owner = User.objects.create_user(username="o2", password="pass123", email="o2@example.com")
    cat = RoomCategorie.objects.create(name="Any2", active=True)

    Room.objects.create(title="Near", category=cat, price_per_month=800, property_owner=owner,
                        latitude=51.51, longitude=-0.10)
    Room.objects.create(title="Mid", category=cat, price_per_month=850, property_owner=owner,
                        latitude=51.60, longitude=-0.20)
    Room.objects.create(title="Far", category=cat, price_per_month=900, property_owner=owner,
                        latitude=52.00, longitude=0.00)

    client = APIClient()
    url = reverse("v1:search-rooms")

    # Ascending distance
    r1 = client.get(url, {"postcode": "SW1A 1AA", "radius_miles": 200, "ordering": "distance_miles"})
    assert r1.status_code == 200, r1.data
    results1 = r1.data.get("results", r1.data)
    titles1 = [it["title"] for it in results1[:3]]
    assert titles1 == ["Near", "Mid", "Far"]

    # Descending distance
    r2 = client.get(url, {"postcode": "SW1A 1AA", "radius_miles": 200, "ordering": "-distance_miles"})
    assert r2.status_code == 200, r2.data
    results2 = r2.data.get("results", r2.data)
    titles2 = [it["title"] for it in results2[:3]]
    assert titles2 == ["Far", "Mid", "Near"]
