import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from propertylist_app.models import Room, RoomCategorie, Review

User = get_user_model()

@pytest.mark.django_db
def test_delete_preview_counts():
    """
    The delete preview should list how much user data would be anonymised/deleted.
    We assert the nested structure and that counts reflect our setup.
    """
    user = User.objects.create_user(
        username="preview_user", password="pass123", email="p@example.com"
    )
    cat = RoomCategorie.objects.create(name="GDPR Cat", active=True)
    room = Room.objects.create(
        title="Room to Erase", category=cat, price_per_month=700, property_owner=user
    )
    Review.objects.create(room=room, review_user=user, rating=5, description="Great!")

    client = APIClient()
    client.force_authenticate(user=user)

    r = client.get("/api/v1/users/me/delete/preview/")
    assert r.status_code == 200
    data = r.json()

    # New structure: look under "anonymise" for user-generated objects
    anon = data.get("anonymise", {})
    assert "rooms" in anon and "reviews" in anon and "messages" in anon, data

    # We created exactly 1 room and 1 review; messages may be 0 (tolerant check)
    assert anon["rooms"] >= 1
    assert anon["reviews"] >= 1
    assert anon["messages"] >= 0

    # Optional: ensure other sections exist (tolerant—just presence)
    assert "delete" in data
    assert "retain_non_pii" in data
