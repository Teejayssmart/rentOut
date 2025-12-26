import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, SavedRoom


@pytest.mark.django_db
def test_save_toggle_creates_and_deletes():
    user = User.objects.create_user(username="tee", password="pass123", email="t@example.com")
    cat = RoomCategorie.objects.create(name="Central", active=True)
    room = Room.objects.create(title="Nice Room", category=cat, price_per_month=900, property_owner=user)

    client = APIClient()
    client.force_authenticate(user=user)

    toggle_url = reverse("v1:room-save-toggle", kwargs={"pk": room.pk})

    # 1) First toggle -> saved
    r1 = client.post(toggle_url)
    assert r1.status_code in (200, 201), r1.data
    assert r1.data.get("saved") is True
    assert SavedRoom.objects.filter(user=user, room=room).exists()

    # 2) Second toggle -> unsaved
    r2 = client.post(toggle_url)
    assert r2.status_code in (200, 201), r2.data
    assert r2.data.get("saved") is False
    assert not SavedRoom.objects.filter(user=user, room=room).exists()


@pytest.mark.django_db
def test_my_saved_rooms_ordering_by_most_recent_first():
    user = User.objects.create_user(username="tee2", password="pass123", email="t2@example.com")
    cat = RoomCategorie.objects.create(name="West", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")

    room1 = Room.objects.create(title="Room 1", category=cat, price_per_month=500, property_owner=owner)
    room2 = Room.objects.create(title="Room 2", category=cat, price_per_month=600, property_owner=owner)
    room3 = Room.objects.create(title="Room 3", category=cat, price_per_month=700, property_owner=owner)

    client = APIClient()
    client.force_authenticate(user=user)

    # Save in order: 1, then 2, then 3 (3 should appear first by default)
    client.post(reverse("v1:room-save-toggle", kwargs={"pk": room1.pk}))
    client.post(reverse("v1:room-save-toggle", kwargs={"pk": room2.pk}))
    client.post(reverse("v1:room-save-toggle", kwargs={"pk": room3.pk}))

    url = reverse("v1:my-saved-rooms")
    r = client.get(url)
    assert r.status_code == 200, r.data

    titles = [item["title"] for item in r.data.get("results", r.data)]
    # Default ordering is "-saved_at" (most recently saved first)
    assert titles[0] == "Room 3"
    assert set(titles[:3]) == {"Room 1", "Room 2", "Room 3"}
