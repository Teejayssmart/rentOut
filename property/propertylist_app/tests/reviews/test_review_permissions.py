import pytest
from datetime import timedelta

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import RoomCategorie, Room, Booking, Review


@pytest.mark.django_db
def test_user_cannot_review_booking_if_not_participant():
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Flat", active=True)
    room = Room.objects.create(title="Owner room", category=cat, price_per_month=900, property_owner=owner)

    tenant = User.objects.create_user(username="tenant", password="pass123", email="t@example.com")
    booking = Booking.objects.create(
        user=tenant,
        room=room,
        start=timezone.now() - timedelta(days=40),
        end=timezone.now() - timedelta(days=35),
        status=Booking.STATUS_ACTIVE,
    )

    stranger = User.objects.create_user(username="stranger", password="pass123", email="s@example.com")
    client = APIClient()
    client.force_authenticate(user=stranger)

    url = reverse("api:booking-reviews-create", kwargs={"booking_id": booking.id})
    r = client.post(url, {"notes": "Nice place", "review_flags": ["responsive"]}, format="json")

    assert r.status_code in (400, 403)


@pytest.mark.django_db
def test_tenant_can_create_review_for_booking():
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Flat", active=True)
    room = Room.objects.create(title="Test Room", category=cat, price_per_month=900, property_owner=owner)

    tenant = User.objects.create_user(username="tenant2", password="pass123", email="t2@example.com")
    booking = Booking.objects.create(
        user=tenant,
        room=room,
        start=timezone.now() - timedelta(days=10),
        end=timezone.now() - timedelta(days=5),

        status=Booking.STATUS_ACTIVE,
    )

    client = APIClient()
    client.force_authenticate(user=tenant)

    url = reverse("api:booking-reviews-create", kwargs={"booking_id": booking.id})
    r = client.post(url, {"notes": "Amazing!", "review_flags": ["responsive"]}, format="json")

    assert r.status_code == 201, r.data
    assert Review.objects.filter(booking=booking, reviewer=tenant).count() == 1
