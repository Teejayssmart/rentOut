import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.contrib.auth import get_user_model

from propertylist_app.models import Room, RoomCategorie

User = get_user_model()


@pytest.mark.django_db
def test_unpublish_requires_authentication():
    cat = RoomCategorie.objects.create(name="General", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    room = Room.objects.create(title="R1", category=cat, price_per_month=500, property_owner=owner)

    client = APIClient()
    url = reverse("v1:room-unpublish", kwargs={"pk": room.pk})

    r = client.post(url, {}, format="json")
    assert r.status_code in (401, 403)  # depends on your auth settings


@pytest.mark.django_db
def test_owner_can_unpublish_sets_hidden_and_returns_200():
    cat = RoomCategorie.objects.create(name="General", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    room = Room.objects.create(title="R1", category=cat, price_per_month=500, property_owner=owner, status="active")

    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("v1:room-unpublish", kwargs={"pk": room.pk})
    r = client.post(url, {}, format="json")

    assert r.status_code == 200, r.content
    assert r.data["status"] == "hidden"
    assert r.data["listing_state"] == "hidden"

    room.refresh_from_db()
    assert room.status == "hidden"


@pytest.mark.django_db
def test_non_owner_cannot_unpublish_403():
    cat = RoomCategorie.objects.create(name="General", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    other = User.objects.create_user(username="other", password="pass123", email="other@x.com")

    room = Room.objects.create(title="R1", category=cat, price_per_month=500, property_owner=owner, status="active")

    client = APIClient()
    client.force_authenticate(user=other)

    url = reverse("v1:room-unpublish", kwargs={"pk": room.pk})
    r = client.post(url, {}, format="json")

    assert r.status_code == 403, r.content


@pytest.mark.django_db
def test_unpublish_is_idempotent_if_already_hidden():
    cat = RoomCategorie.objects.create(name="General", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    room = Room.objects.create(title="R1", category=cat, price_per_month=500, property_owner=owner, status="hidden")

    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("v1:room-unpublish", kwargs={"pk": room.pk})
    r = client.post(url, {}, format="json")

    assert r.status_code == 200, r.content
    room.refresh_from_db()
    assert room.status == "hidden"
