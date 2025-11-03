import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from propertylist_app.models import Room, RoomCategorie

User = get_user_model()


@pytest.mark.django_db
def test_room_update_owner_only():
    """
    Only the room owner can update the listing.
    Other users must receive 403 Forbidden.
    """
    owner = User.objects.create_user(username="john", password="pass123", email="j@example.com")
    stranger = User.objects.create_user(username="mark", password="pass123", email="m@example.com")
    cat = RoomCategorie.objects.create(name="Private", active=True)
    room = Room.objects.create(
        title="Owner Room",
        category=cat,
        price_per_month=850,
        property_owner=owner,
        status="active",
    )

    client = APIClient()

    # try to update as non-owner → forbidden
    client.force_authenticate(user=stranger)
    r_forbidden = client.patch(f"/api/v1/rooms/{room.id}/", {"title": "Changed"}, format="json")
    assert r_forbidden.status_code == 403

    # try to update as owner → allowed
    client.force_authenticate(user=owner)
    r_allowed = client.patch(f"/api/v1/rooms/{room.id}/", {"title": "Updated Title"}, format="json")
    assert r_allowed.status_code in (200, 202)

    room.refresh_from_db()
    assert room.title == "Updated Title"
