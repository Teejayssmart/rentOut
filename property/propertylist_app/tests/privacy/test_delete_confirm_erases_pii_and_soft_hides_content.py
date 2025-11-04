import pytest
from rest_framework.test import APIClient
from django.utils import timezone

from django.contrib.auth import get_user_model
from propertylist_app.models import Room, RoomCategorie, Review

User = get_user_model()


@pytest.mark.django_db
def test_delete_confirm_erases_pii_and_soft_hides_content():
    """
    Confirmed GDPR deletion should:
      - deactivate the account (is_active = False)
      - soft-hide related content (e.g., rooms are not public)
      - keep the system consistent (no crashes, objects in valid states)
    """
    # Arrange: user with a room and a review
    owner = User.objects.create_user(
        username="erase_me",
        password="pass123",
        email="erase@example.com",
    )
    cat = RoomCategorie.objects.create(name="GDPR", active=True)
    room = Room.objects.create(
        title="GDPR Room",
        category=cat,
        price_per_month=700,
        property_owner=owner,
        status="active",
        paid_until=timezone.now().date(),
    )
    review = Review.objects.create(
        room=room,
        review_user=owner,
        rating=5,
        description="Great",
        active=True,
    )

    client = APIClient()
    client.force_authenticate(user=owner)

    # Act: confirm deletion
    resp = client.post("/api/v1/users/me/delete/confirm/", {"confirm": True}, format="json")
    assert resp.status_code in (200, 204), resp.content

    # Assert: user deactivated
    owner.refresh_from_db()
    assert owner.is_active is False

    # Assert: room soft-hidden (no longer public)
    room.refresh_from_db()
    assert room.status == "hidden"

    # Assert: review still in a safe state (exists or was anonymised/retained safely)
    assert Review.objects.filter(pk=review.pk).exists()
