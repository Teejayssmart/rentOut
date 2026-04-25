import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from propertylist_app.models import Room, RoomCategorie

User = get_user_model()


def _extract_items(payload):
    """
    Support both old paginated shape:
      {"results": [...]}

    and newer envelope shapes such as:
      {"ok": true, "data": [...]}
      {"ok": true, "data": {"results": [...]}}

    and plain list responses.
    """
    if isinstance(payload, list):
        return payload

    if "results" in payload and isinstance(payload["results"], list):
        return payload["results"]

    data = payload.get("data")

    if isinstance(data, list):
        return data

    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data["results"]

    raise AssertionError(f"Unexpected response shape: {payload}")


@pytest.mark.django_db
def test_hidden_room_excluded_from_search_and_rooms_alt():
    owner = User.objects.create_user(username="o", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Any", active=True)

    Room.objects.create(
        title="Visible Room",
        description="...",
        price_per_month=900,
        location="London SW1A 1AA",
        category=cat,
        property_owner=owner,
        status="active",
    )
    Room.objects.create(
        title="Hidden Room",
        description="...",
        price_per_month=950,
        location="London SW1A 2AA",
        category=cat,
        property_owner=owner,
        status="hidden",
    )

    client = APIClient()

    # /api/v1/rooms-alt/ (public list)
    url_list = reverse("v1:room-list-alt")
    r1 = client.get(url_list)
    assert r1.status_code == 200
    items1 = _extract_items(r1.json())
    titles = [x["title"] for x in items1]
    assert "Visible Room" in titles
    assert "Hidden Room" not in titles

    # /api/v1/search/rooms/?q=Room (public search)
    url_search = reverse("v1:search-rooms")
    r2 = client.get(url_search, {"q": "Room"})
    assert r2.status_code == 200
    items2 = _extract_items(r2.json())
    titles2 = [x["title"] for x in items2]
    assert "Visible Room" in titles2
    assert "Hidden Room" not in titles2