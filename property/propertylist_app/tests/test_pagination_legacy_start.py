import pytest

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import RoomCategorie, Room


@pytest.mark.django_db
def test_rooms_list_supports_legacy_start_param():
    cat = RoomCategorie.objects.create(name="Standard", active=True)

    User = get_user_model()
    owner = User.objects.create_user(username="pagination_owner_1", password="pass12345")

    for i in range(5):
        Room.objects.create(
            title=f"Room {i}",
            category=cat,
            property_owner=owner,
            price_per_month=500 + i,
            status="active",
        )

    client = APIClient()
    url = reverse("v1:room-list")

    r_offset = client.get(url, {"limit": 2, "offset": 0})
    r_start = client.get(url, {"limit": 2, "start": 0})

    assert r_offset.status_code == 200
    assert r_start.status_code == 200
    assert r_offset.data["results"] == r_start.data["results"]


@pytest.mark.django_db
def test_rooms_list_legacy_start_affects_pagination_links_like_offset():
    cat = RoomCategorie.objects.create(name="Standard Legacy", active=True)

    User = get_user_model()
    owner = User.objects.create_user(username="pagination_owner_2", password="pass12345")

    for i in range(5):
        Room.objects.create(
            title=f"Room {i}",
            category=cat,
            property_owner=owner,
            price_per_month=500 + i,
            status="active",
        )

    client = APIClient()
    url = reverse("v1:room-list")

    r = client.get(url, {"limit": 2, "start": 2})

    assert r.status_code == 200
    assert "count" in r.data
    assert "next" in r.data
    assert "previous" in r.data
    assert "results" in r.data

    assert "offset=4" in r.data["next"]
    assert "offset=0" in r.data["previous"]