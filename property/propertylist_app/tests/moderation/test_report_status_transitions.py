import pytest
from django.contrib.auth.models import User

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


def test_report_status_transition_matrix_enforced_via_patch(api_client):
    reporter = _mk_user("reporter")
    staff = _mk_user("mod", is_staff=True)
    landlord = _mk_user("landlord")
    room = _mk_room(landlord, status="active")

    # reporter creates report (should be 'open' by default) :contentReference[oaicite:5]{index=5}
    api_client.force_authenticate(user=reporter)
    r = api_client.post(
        "/api/v1/reports/",
        {"target_type": "room", "object_id": room.id, "reason": "abuse", "details": "spam"},
        format="json",
    )
    assert r.status_code in (200, 201)

    report_id = Report.objects.latest("id").id
    report = Report.objects.get(id=report_id)
    assert report.status == "open"

    # staff moves open -> in_review (allowed)
    api_client.force_authenticate(user=staff)
    r = api_client.patch(
        f"/api/v1/moderation/reports/{report_id}/",
        {"status": "in_review"},
        format="json",
    )
    assert r.status_code == 200
    report.refresh_from_db()
    assert report.status == "in_review"

    # staff moves in_review -> resolved (allowed)
    r = api_client.patch(
        f"/api/v1/moderation/reports/{report_id}/",
        {"status": "resolved"},
        format="json",
    )
    assert r.status_code == 200
    report.refresh_from_db()
    assert report.status == "resolved"

    # resolved -> in_review (NOT allowed; terminal)
    r = api_client.patch(
        f"/api/v1/moderation/reports/{report_id}/",
        {"status": "in_review"},
        format="json",
    )
    assert r.status_code == 400
    report.refresh_from_db()
    assert report.status == "resolved"


def test_report_status_transition_matrix_enforced_via_moderate_action(api_client):
    reporter = _mk_user("reporter2")
    staff = _mk_user("mod2", is_staff=True)
    landlord = _mk_user("landlord2")
    room = _mk_room(landlord, status="active")

    api_client.force_authenticate(user=reporter)
    r = api_client.post(
        "/api/v1/reports/",
        {"target_type": "room", "object_id": room.id, "reason": "abuse", "details": "spam"},
        format="json",
    )
    assert r.status_code in (200, 201)

    report_id = Report.objects.latest("id").id

    # open -> resolved (allowed)
    api_client.force_authenticate(user=staff)
    r = api_client.post(
        f"/api/v1/reports/{report_id}/moderate/",
        {"action": "resolve", "resolution_notes": "ok"},
        format="json",
    )
    assert r.status_code == 200
    report = Report.objects.get(id=report_id)
    assert report.status == "resolved"

    # resolved -> rejected (NOT allowed)
    r = api_client.post(
        f"/api/v1/reports/{report_id}/moderate/",
        {"action": "reject", "resolution_notes": "too late"},
        format="json",
    )
    assert r.status_code == 400
    report.refresh_from_db()
    assert report.status == "resolved"
