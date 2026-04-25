import pytest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie


@pytest.mark.django_db
def test_hidden_room_not_in_list_or_search():
    cat = RoomCategorie.objects.create(name="Standard", active=True)

    User = get_user_model()
    owner = User.objects.create_user(
        username="room_owner",
        password="pass12345",
    )

    Room.objects.create(
        title="Public Room",
        category=cat,
        property_owner=owner,
        price_per_month=600,
        status="active",
    )

    Room.objects.create(
        title="Hidden Room",
        category=cat,
        property_owner=owner,
        price_per_month=700,
        status="hidden",
    )

    Room.objects.create(
        title="Expired Room",
        category=cat,
        property_owner=owner,
        price_per_month=800,
        status="active",
        paid_until=timezone.now().date() - timedelta(days=1),
    )

    client = APIClient()

    r_list = client.get("/api/v1/rooms/")
    assert r_list.status_code == 200
    payload = r_list.json()
    rooms = payload["results"]
    titles = [r["title"] for r in rooms]

    assert "Public Room" in titles
    assert "Hidden Room" not in titles
    assert "Expired Room" not in titles

    r_search = client.get("/api/v1/search/rooms/?q=Room")
    assert r_search.status_code == 200
    data = r_search.json()
    results = data if isinstance(data, list) else data.get("results", data)
    titles = [r["title"] for r in results]

    assert "Public Room" in titles
    assert "Hidden Room" not in titles
    assert "Expired Room" not in titles