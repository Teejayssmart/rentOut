import pytest
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from propertylist_app.models import Room, RoomCategorie, Report

pytestmark = pytest.mark.django_db


def _mk_user(username: str, *, is_staff: bool = False) -> User:
    return User.objects.create_user(
        username=username,
        password="pass12345",
        is_staff=is_staff,
    )


def _mk_room(owner: User, status: str = "active") -> Room:
    cat = RoomCategorie.objects.create(name="General", key=f"general-{owner.username}")
    return Room.objects.create(
        title=f"Room {owner.username}",
        description="desc",
        price_per_month="500.00",
        location="London",
        category=cat,
        property_owner=owner,
        property_type="flat",
        status=status,
    )


def _mk_report(reporter: User, *, room: Room) -> Report:
    return Report.objects.create(
        reporter=reporter,
        target_type="room",
        content_type=ContentType.objects.get_for_model(Room),
        object_id=room.id,
        reason="abuse",
        details="spam",
    )


def test_patch_update_sets_handled_by_and_updates_timestamp(api_client):
    reporter = _mk_user("reporter_audit_1")
    staff = _mk_user("staff_audit_1", is_staff=True)
    landlord = _mk_user("landlord_audit_1")
    room = _mk_room(landlord)
    report = _mk_report(reporter, room=room)

    old_updated_at = report.updated_at
    assert report.handled_by is None

    api_client.force_authenticate(user=staff)
    r = api_client.patch(
        f"/api/v1/moderation/reports/{report.id}/",
        {"status": "in_review", "resolution_notes": "reviewing"},
        format="json",
    )
    assert r.status_code == 200

    report.refresh_from_db()
    assert report.handled_by_id == staff.id
    assert report.updated_at >= old_updated_at
    assert report.resolution_notes == "reviewing"


def test_moderate_action_sets_handled_by_and_updates_timestamp(api_client):
    reporter = _mk_user("reporter_audit_2")
    staff = _mk_user("staff_audit_2", is_staff=True)
    landlord = _mk_user("landlord_audit_2")
    room = _mk_room(landlord)
    report = _mk_report(reporter, room=room)

    old_updated_at = report.updated_at
    assert report.handled_by is None

    api_client.force_authenticate(user=staff)
    r = api_client.post(
        f"/api/v1/reports/{report.id}/moderate/",
        {"action": "resolve", "resolution_notes": "done"},
        format="json",
    )
    assert r.status_code == 200

    report.refresh_from_db()
    assert report.handled_by_id == staff.id
    assert report.updated_at >= old_updated_at
    assert report.status == "resolved"
    assert report.resolution_notes == "done"
