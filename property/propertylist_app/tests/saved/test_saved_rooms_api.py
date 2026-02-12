import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, SavedRoom



@pytest.mark.django_db
def test_save_is_idempotent_and_unsave_is_idempotent():
    user = User.objects.create_user(username="tee", password="pass123", email="t@example.com")
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Central", active=True)
    room = Room.objects.create(title="Nice Room", category=cat, price_per_month=900, property_owner=owner)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("v1:room-save", kwargs={"pk": room.pk})





    # POST save twice -> still only one SavedRoom
    r2 = client.post(url)
    assert r2.status_code in (200, 201), r2.data
    assert r2.data.get("ok") is True
    assert r2.data.get("data", {}).get("saved") is True
    assert SavedRoom.objects.filter(user=user, room=room).count() == 1


    r2 = client.post(url)
    assert r2.status_code in (200, 201), r2.data
    assert r2.data.get("ok") is True
    assert r2.data.get("data", {}).get("saved") is True
    assert SavedRoom.objects.filter(user=user, room=room).count() == 1

    # DELETE unsave twice -> no-op, stays unsaved
    r3 = client.delete(url)
    assert r3.status_code in (200, 204), getattr(r3, "data", None)
    assert SavedRoom.objects.filter(user=user, room=room).count() == 0

    r4 = client.delete(url)
    assert r4.status_code in (200, 204), getattr(r4, "data", None)
    assert SavedRoom.objects.filter(user=user, room=room).count() == 0



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
