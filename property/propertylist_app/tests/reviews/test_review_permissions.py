import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient
from propertylist_app.models import RoomCategorie, Room, Review


@pytest.mark.django_db
def test_user_cannot_review_own_room():
    """Owner cannot review their own room."""
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Flat", active=True)
    room = Room.objects.create(title="Owner’s room", category=cat, price_per_month=900, property_owner=owner)

    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("v1:room-reviews-create", kwargs={"pk": room.pk})
    r = client.post(url, {"rating": 4, "description": "Nice place"}, format="json")

    assert r.status_code == 400
    assert "You cannot review your own room." in str(r.data)


@pytest.mark.django_db
def test_user_can_create_and_edit_their_review():
    """A normal user can post and update their own review."""
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
    reviewer = User.objects.create_user(username="reviewer", password="pass123", email="r@example.com")
    cat = RoomCategorie.objects.create(name="Flat", active=True)
    room = Room.objects.create(title="Test Room", category=cat, price_per_month=900, property_owner=owner)

    client = APIClient()
    client.force_authenticate(user=reviewer)

    url = reverse("v1:room-reviews-create", kwargs={"pk": room.pk})
    r = client.post(url, {"rating": 5, "description": "Amazing!"}, format="json")
    assert r.status_code == 201

    review_id = Review.objects.get(review_user=reviewer, room=room).id

    update_url = reverse("v1:review-detail", kwargs={"pk": review_id})
    r2 = client.put(update_url, {"rating": 4, "description": "Actually, very good"}, format="json")
    assert r2.status_code == 200
    assert r2.data["rating"] == 4
