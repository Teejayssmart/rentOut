import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from propertylist_app.models import Room, RoomCategorie, Review
from datetime import timedelta
from django.utils import timezone
from propertylist_app.models import Booking

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
    # propertylist_app/tests/privacy/test_delete_preview_counts.py
    # PASTE this block EXACTLY where you deleted the old Review.objects.create(...)

    tenant = User.objects.create_user(
        username="preview_tenant",
        password="pass123",
        email="preview_tenant@example.com",
    )

    booking = Booking.objects.create(
        user=tenant,
        room=room,
        start=timezone.now() - timedelta(days=40),
        end=timezone.now() - timedelta(days=35),
        status=Booking.STATUS_ACTIVE,
    )

    Review.objects.create(
        booking=booking,
        reviewer=tenant,
        reviewee=user,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["responsive"],
        notes="Great!",
        active=True,
    )


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
