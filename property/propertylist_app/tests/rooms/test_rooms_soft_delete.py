import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from propertylist_app.models import Room, RoomCategorie

User = get_user_model()


@pytest.mark.django_db
def test_owner_can_soft_delete_and_room_disappears_from_alive():
    # Owner + category + room
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Flat", active=True)
    room = Room.objects.create(
        title="My Room",
        description="Nice place",
        price_per_month=800,
        location="SW1A 1AA",
        category=cat,
        property_owner=owner,
        property_type="flat",
    )

    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("v1:room-soft-delete", kwargs={"pk": room.pk})
    r = client.post(url)
    assert r.status_code == 200, r.data

    room.refresh_from_db()
    assert room.is_deleted is True
    # Not returned by "alive()" queries anymore
    assert not Room.objects.alive().filter(pk=room.pk).exists()


@pytest.mark.django_db
def test_non_owner_cannot_soft_delete_someone_elses_room():
    owner = User.objects.create_user(username="owner2", password="pass123", email="o2@example.com")
    intruder = User.objects.create_user(username="intruder", password="pass123", email="i@example.com")
    cat = RoomCategorie.objects.create(name="Studio", active=True)
    room = Room.objects.create(
        title="Owner2 Room",
        description="Neat",
        price_per_month=900,
        location="EC1A 1BB",
        category=cat,
        property_owner=owner,
        property_type="studio",
    )

    client = APIClient()
    client.force_authenticate(user=intruder)

    url = reverse("v1:room-soft-delete", kwargs={"pk": room.pk})
    r = client.post(url)
    assert r.status_code == 403, r.data

    room.refresh_from_db()
    assert room.is_deleted is False


@pytest.mark.django_db
def test_soft_deleted_room_not_in_public_rooms_endpoint():
    owner = User.objects.create_user(username="own3", password="pass123", email="o3@example.com")
    cat = RoomCategorie.objects.create(name="House", active=True)
    room = Room.objects.create(
        title="Temp House",
        description="To be deleted",
        price_per_month=700,
        location="W1A 1HQ",
        category=cat,
        property_owner=owner,
        property_type="house",
    )

    c = APIClient()
    c.force_authenticate(user=owner)
    # Soft delete first
    soft_url = reverse("v1:room-soft-delete", kwargs={"pk": room.pk})
    assert c.post(soft_url).status_code == 200

    # Public list should not include it
    list_url = reverse("v1:room-list")
    r = c.get(list_url)
    assert r.status_code == 200
    ids = [item["id"] for item in r.data]
    assert room.id not in ids
