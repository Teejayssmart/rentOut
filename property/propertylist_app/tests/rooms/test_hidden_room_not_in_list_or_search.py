import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from propertylist_app.models import Room, RoomCategorie


@pytest.mark.django_db
def test_hidden_room_not_in_list_or_search():
    """
    Hidden or expired rooms must not appear in the public room list or in search results.
    """
    cat = RoomCategorie.objects.create(name="Standard", active=True)

    Room.objects.create(title="Public Room", category=cat, price_per_month=600, status="active")
    Room.objects.create(title="Hidden Room", category=cat, price_per_month=700, status="hidden")
    Room.objects.create(
        title="Expired Room",
        category=cat,
        price_per_month=800,
        status="active",
        paid_until=timezone.now().date() - timedelta(days=1),
    )

    client = APIClient()

    # room list should only show active
    r_list = client.get("/api/v1/rooms/")
    assert r_list.status_code == 200
    titles = [r["title"] for r in r_list.json()]
    assert "Public Room" in titles
    assert "Hidden Room" not in titles
    assert "Expired Room" not in titles

    # search should only show active
    r_search = client.get("/api/v1/search/rooms/?q=Room")
    data = r_search.json()
    results = data if isinstance(data, list) else data.get("results", data)
    titles = [r["title"] for r in results]
    assert "Public Room" in titles
    assert "Hidden Room" not in titles
    assert "Expired Room" not in titles
