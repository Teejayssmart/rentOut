import pytest
from datetime import timedelta
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from propertylist_app.models import Booking, Room, RoomCategorie

User = get_user_model()


@pytest.mark.django_db
def test_booking_delete_requires_authentication():
    cat = RoomCategorie.objects.create(name="General", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    user = User.objects.create_user(username="u1", password="pass123", email="u1@x.com")
    room = Room.objects.create(title="R1", category=cat, price_per_month=500, property_owner=owner)

    b = Booking.objects.create(
        user=user,
        room=room,
        start=timezone.now() + timedelta(days=2),
        end=timezone.now() + timedelta(days=2, hours=1),
    )

    client = APIClient()
    url = reverse("v1:booking-delete", kwargs={"pk": b.pk})
    r = client.delete(url)
    assert r.status_code in (401, 403)


@pytest.mark.django_db
def test_owner_can_delete_future_booking_204():
    cat = RoomCategorie.objects.create(name="General", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    user = User.objects.create_user(username="u1", password="pass123", email="u1@x.com")
    room = Room.objects.create(title="R1", category=cat, price_per_month=500, property_owner=owner)

    b = Booking.objects.create(
        user=user,
        room=room,
        start=timezone.now() + timedelta(days=2),
        end=timezone.now() + timedelta(days=2, hours=1),
    )

    client = APIClient()
    client.force_authenticate(user=owner)


    url = reverse("v1:booking-delete", kwargs={"pk": b.pk})
    r = client.delete(url)


    assert r.status_code == 204
    b.refresh_from_db()
    assert b.is_deleted is True



@pytest.mark.django_db
def test_non_owner_cannot_delete_booking_404():
    cat = RoomCategorie.objects.create(name="General", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    user1 = User.objects.create_user(username="u1", password="pass123", email="u1@x.com")
    user2 = User.objects.create_user(username="u2", password="pass123", email="u2@x.com")
    room = Room.objects.create(title="R1", category=cat, price_per_month=500, property_owner=owner)

    b = Booking.objects.create(
        user=user1,
        room=room,
        start=timezone.now() + timedelta(days=2),
        end=timezone.now() + timedelta(days=2, hours=1),
    )

    client = APIClient()
    client.force_authenticate(user=user2)



    url = reverse("v1:booking-delete", kwargs={"pk": b.pk})
    r = client.delete(url)


    # because queryset is filtered by user, non-owner gets 404
    assert r.status_code == 404


@pytest.mark.django_db
def test_cannot_delete_started_booking_400():
    cat = RoomCategorie.objects.create(name="General", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    user = User.objects.create_user(username="u1", password="pass123", email="u1@x.com")
    room = Room.objects.create(title="R1", category=cat, price_per_month=500, property_owner=owner)

    b = Booking.objects.create(
        user=user,
        room=room,
        start=timezone.now() - timedelta(hours=1),
        end=timezone.now() + timedelta(hours=1),
    )

    client = APIClient()
    client.force_authenticate(user=owner)


    url = reverse("v1:booking-delete", kwargs={"pk": b.pk})
    r = client.delete(url)


    assert r.status_code == 400
