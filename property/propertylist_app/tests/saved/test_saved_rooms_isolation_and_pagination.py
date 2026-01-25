import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, SavedRoom


@pytest.mark.django_db
def test_user_a_cannot_see_user_b_saved_rooms():
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
    user_a = User.objects.create_user(username="a", password="pass123", email="a@example.com")
    user_b = User.objects.create_user(username="b", password="pass123", email="b@example.com")
    cat = RoomCategorie.objects.create(name="West", active=True)

    room_a = Room.objects.create(title="Room A", category=cat, price_per_month=500, property_owner=owner)
    room_b = Room.objects.create(title="Room B", category=cat, price_per_month=600, property_owner=owner)

    SavedRoom.objects.create(user=user_a, room=room_a)
    SavedRoom.objects.create(user=user_b, room=room_b)

    client = APIClient()
    client.force_authenticate(user=user_a)

    url = reverse("v1:my-saved-rooms")
    r = client.get(url)
    assert r.status_code == 200

    items = r.data.get("results", r.data)
    ids = [x["id"] for x in items]
    assert room_a.id in ids
    assert room_b.id not in ids


@pytest.mark.django_db
def test_my_saved_rooms_is_paginated_if_results_key_present():
    user = User.objects.create_user(username="tee_pag", password="pass123", email="tp@example.com")
    owner = User.objects.create_user(username="owner_pag", password="pass123", email="op@example.com")
    cat = RoomCategorie.objects.create(name="Cat", active=True)

    rooms = [
        Room.objects.create(title=f"Room {i}", category=cat, price_per_month=400 + i, property_owner=owner)
        for i in range(1, 8)
    ]
    for room in rooms:
        SavedRoom.objects.create(user=user, room=room)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("v1:my-saved-rooms")

    r = client.get(url)
    assert r.status_code == 200

    # If pagination is enabled, DRF returns {"count","next","previous","results"}
    if isinstance(r.data, dict) and "results" in r.data:
        assert "count" in r.data
        assert isinstance(r.data["results"], list)
        assert len(r.data["results"]) > 0
