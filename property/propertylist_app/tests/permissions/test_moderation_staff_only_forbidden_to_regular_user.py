import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient
from propertylist_app.models import Room, RoomCategorie, Report

User = get_user_model()


@pytest.mark.django_db
def test_moderation_staff_only_forbidden_to_regular_user():
    """
    Only staff users can perform moderation actions.
    Regular users must receive 403 Forbidden.
    """
    # create regular and staff users
    regular = User.objects.create_user(username="alice", password="pass123", email="a@x.com")
    staff = User.objects.create_user(username="mod", password="pass123", email="m@x.com", is_staff=True)

    # create a room and a report to moderate
    cat = RoomCategorie.objects.create(name="Perms", active=True)
    room = Room.objects.create(title="Room A", category=cat, price_per_month=500, status="active")

    # attach report to the room
    report = Report.objects.create(
        reporter=regular,
        target_type="room",
        content_type=ContentType.objects.get_for_model(Room),
        object_id=room.id,
        reason="abuse",
        details="Inappropriate content",
    )

    client = APIClient()

    # regular user cannot moderate → 403
    client.force_authenticate(user=regular)
    r_forbidden = client.post(f"/api/v1/reports/{report.id}/moderate/", {"action": "resolve"}, format="json")
    assert r_forbidden.status_code == 403

    # staff user can moderate → 200
    client.force_authenticate(user=staff)
    r_allowed = client.post(f"/api/v1/reports/{report.id}/moderate/", {"action": "resolve"}, format="json")
    assert r_allowed.status_code in (200, 204)
