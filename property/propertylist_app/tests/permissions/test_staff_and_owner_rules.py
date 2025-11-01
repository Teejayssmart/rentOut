import pytest
from rest_framework.test import APIClient
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from propertylist_app.models import Room, RoomCategorie, Report


@pytest.mark.django_db
def test_moderation_staff_only_forbidden_to_regular_user():
    """
    Regular users must NOT be able to moderate reports (403).
    Staff users CAN update a report (200).
    """
    # Users
    regular = User.objects.create_user(username="alice", password="pass123", email="a@x.com")
    staff = User.objects.create_user(username="mod", password="pass123", email="m@x.com", is_staff=True)

    # A room + a report to moderate
    cat = RoomCategorie.objects.create(name="Perms", active=True)
    room = Room.objects.create(title="Room A", category=cat, price_per_month=500, status="active")

    # IMPORTANT: reporter is required (NOT NULL), and Report uses a GenericForeignKey.
    report = Report.objects.create(
        reporter=regular,
        target_type="room",
        content_type=ContentType.objects.get_for_model(Room),
        object_id=room.id,
        reason="abuse",
        details="Inappropriate content",
    )

    url = f"/api/v1/moderation/reports/{report.id}/"

    # ---- Regular user: forbidden
    c = APIClient()
    c.force_authenticate(user=regular)
    r_forbid = c.patch(url, {"status": "in_review"}, format="json")
    assert r_forbid.status_code == 403, r_forbid.content

    # ---- Staff user: allowed
    c.force_authenticate(user=staff)
    r_ok = c.patch(url, {"status": "in_review", "resolution_notes": "Checking"}, format="json")
    assert r_ok.status_code == 200, r_ok.content
    assert r_ok.json().get("status") in {"in_review", "resolved", "rejected"}



@pytest.mark.django_db
def test_room_update_owner_only():
    """
    Only the listing owner can edit their room; other authenticated users get 403.
    """
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    other = User.objects.create_user(username="intruder", password="pass123", email="i@x.com")

    cat = RoomCategorie.objects.create(name="OwnerOnly", active=True)
    room = Room.objects.create(
        title="Owner Room",
        category=cat,
        price_per_month=750,
        status="active",
        property_owner=owner,
    )

    url = f"/api/v1/rooms/{room.id}/"

    # ---- Non-owner tries to update → 403
    c = APIClient()
    c.force_authenticate(user=other)
    r_forbid = c.patch(url, {"title": "Hacked Title"}, format="json")
    assert r_forbid.status_code == 403, r_forbid.content

    # ---- Owner updates → 200 and title changed
    c.force_authenticate(user=owner)
    r_ok = c.patch(url, {"title": "Updated by Owner"}, format="json")
    assert r_ok.status_code == 200, r_ok.content
    assert r_ok.json().get("title") == "Updated by Owner"
