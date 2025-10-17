import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from propertylist_app.models import Room, RoomCategorie

User = get_user_model()

@pytest.mark.django_db
def test_hidden_room_excluded_from_search_and_rooms_alt():
    owner = User.objects.create_user(username="o", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Any", active=True)

    active_room = Room.objects.create(
        title="Visible Room",
        description="...",
        price_per_month=900,
        location="London SW1A 1AA",
        category=cat,
        property_owner=owner,
        status="active",
    )
    hidden_room = Room.objects.create(
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
    titles = [x["title"] for x in r1.json()["results"]]
    assert "Visible Room" in titles
    assert "Hidden Room" not in titles

    # /api/v1/search/rooms/?q=Room (public search)
    url_search = reverse("v1:search-rooms")
    r2 = client.get(url_search, {"q": "Room"})
    assert r2.status_code == 200
    titles2 = [x["title"] for x in r2.json()["results"]]
    assert "Visible Room" in titles2
    assert "Hidden Room" not in titles2
