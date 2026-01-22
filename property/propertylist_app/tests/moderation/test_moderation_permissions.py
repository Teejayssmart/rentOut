import pytest
from django.contrib.auth.models import User

from propertylist_app.models import Room, RoomCategorie, Report
from django.contrib.contenttypes.models import ContentType


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


def test_regular_user_forbidden_for_moderation_report_list(api_client):
    user = _mk_user("alice")
    api_client.force_authenticate(user=user)

    r = api_client.get("/api/v1/moderation/reports/?status=open")
    assert r.status_code == 403


def test_regular_user_forbidden_for_moderation_report_update(api_client):
    reporter = _mk_user("reporter")
    landlord = _mk_user("landlord")
    room = _mk_room(landlord)
    report = _mk_report(reporter, room=room)

    user = _mk_user("alice")
    api_client.force_authenticate(user=user)

    r = api_client.patch(
        f"/api/v1/moderation/reports/{report.id}/",
        {"status": "in_review", "resolution_notes": "note"},
        format="json",
    )
    assert r.status_code == 403


def test_regular_user_forbidden_for_report_moderate_action(api_client):
    reporter = _mk_user("reporter2")
    landlord = _mk_user("landlord2")
    room = _mk_room(landlord)
    report = _mk_report(reporter, room=room)

    user = _mk_user("alice2")
    api_client.force_authenticate(user=user)

    r = api_client.post(
        f"/api/v1/reports/{report.id}/moderate/",
        {"action": "resolve", "resolution_notes": "ok"},
        format="json",
    )
    assert r.status_code == 403


def test_regular_user_forbidden_for_room_moderation_status(api_client):
    landlord = _mk_user("landlord3")
    room = _mk_room(landlord, status="active")

    user = _mk_user("alice3")
    api_client.force_authenticate(user=user)

    r = api_client.patch(
        f"/api/v1/moderation/rooms/{room.id}/status/",
        {"status": "hidden"},
        format="json",
    )
    assert r.status_code == 403


def test_staff_user_can_access_all_moderation_endpoints(api_client):
    # Setup: create a room + report
    reporter = _mk_user("reporter_staffcase")
    landlord = _mk_user("landlord_staffcase")
    room = _mk_room(landlord, status="active")
    report = _mk_report(reporter, room=room)

    staff = _mk_user("mod", is_staff=True)
    api_client.force_authenticate(user=staff)

    # list
    r = api_client.get("/api/v1/moderation/reports/?status=open")
    assert r.status_code == 200

    # update report
    r = api_client.patch(
        f"/api/v1/moderation/reports/{report.id}/",
        {"status": "in_review", "resolution_notes": "reviewing"},
        format="json",
    )
    assert r.status_code == 200

    # moderate action
    r = api_client.post(
        f"/api/v1/reports/{report.id}/moderate/",
        {"action": "resolve", "resolution_notes": "done"},
        format="json",
    )
    assert r.status_code == 200

    # room status moderation
    r = api_client.patch(
        f"/api/v1/moderation/rooms/{room.id}/status/",
        {"status": "hidden"},
        format="json",
    )
    assert r.status_code == 200
