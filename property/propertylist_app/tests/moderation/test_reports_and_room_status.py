# property/propertylist_app/tests/moderation/test_reports_and_room_status.py
import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from propertylist_app.models import RoomCategorie, Room, Report

User = get_user_model()


@pytest.mark.django_db
def test_report_create_and_staff_list_update_flow():
    """
    Covers:
      - a normal user can create a Report about a room -> 201
      - non-staff cannot access moderation list -> 403
      - staff can list reports -> 200 and see the created one
      - staff can update report status/notes -> 200 and persisted
      - bad object_id in create -> 400 {"object_id": "..."}
    """
    # Users
    reporter = User.objects.create_user(username="rep", password="pass123", email="rep@example.com")
    staff = User.objects.create_user(username="staff", password="pass123", email="s@example.com", is_staff=True)

    # A room to report
    cat = RoomCategorie.objects.create(name="Moderation", active=True)
    room = Room.objects.create(
        title="Reported Room",
        description="desc",
        price_per_month=500,
        location="SW1A 1AA London",
        category=cat,
        property_owner=reporter,  # owner can be the reporter too, report is generic
        property_type="flat",
    )

    # 1) Reporter creates a report
    c1 = APIClient()
    c1.force_authenticate(user=reporter)
    create_url = reverse("v1:report-create")
    payload = {
        "target_type": "room",
        "object_id": room.id,
        "reason": "spam",
        "details": "Suspicious listing content",
    }
    r1 = c1.post(create_url, payload, format="json")
    assert r1.status_code == 201, r1.data
    report_id = r1.data.get("id")
    assert Report.objects.filter(pk=report_id, target_type="room", object_id=room.id).exists()

    # 2) Non-staff cannot list moderation reports
    list_url = reverse("v1:moderation-report-list")
    r2 = c1.get(list_url)
    assert r2.status_code in (403, 401), r2.data  # expect 403 Forbidden (or 401 if auth policy requires staff)

    # 3) Staff can list moderation reports and see our report
    c_staff = APIClient()
    c_staff.force_authenticate(user=staff)
    r3 = c_staff.get(list_url)
    assert r3.status_code == 200, r3.data
    ids = [item.get("id") for item in r3.data if isinstance(r3.data, list)] or [rep.get("id") for rep in r3.data.get("results", [])]
    assert report_id in ids

    # 4) Staff updates status and resolution notes
    update_url = reverse("v1:moderation-report-update", kwargs={"pk": report_id})
    r4 = c_staff.patch(update_url, {"status": "resolved", "resolution_notes": "Validated spam and resolved"}, format="json")
    assert r4.status_code == 200, r4.data
    r_obj = Report.objects.get(pk=report_id)
    assert r_obj.status == "resolved"
    assert "resolved" in (r_obj.resolution_notes or "").lower()

    # 5) Bad object_id should fail create with field error
    bad = c1.post(create_url, {"target_type": "room", "object_id": 999999, "reason": "spam"}, format="json")
    assert bad.status_code == 400, bad.data
    # Your exception wrapper puts field errors under field_errors/details
    body = bad.data or {}
    # accept either structure
    msg = str(body)
    assert "object_id" in msg


@pytest.mark.django_db
def test_room_moderation_status_staff_only():
    """
    Covers:
      - staff can set a room's moderation status (e.g., hidden) -> 200
      - non-staff cannot -> 403
      - status field actually changes on the Room
    """
    owner = User.objects.create_user(username="own", password="pass123", email="o@example.com")
    staff = User.objects.create_user(username="staff2", password="pass123", email="s2@example.com", is_staff=True)
    normal = User.objects.create_user(username="u", password="pass123", email="u@example.com")

    cat = RoomCategorie.objects.create(name="Mod2", active=True)
    room = Room.objects.create(
        title="Moderate Me",
        description="desc",
        price_per_month=600,
        location="EC1A 1BB London",
        category=cat,
        property_owner=owner,
        property_type="flat",
        status="active",
    )

    url = reverse("v1:moderation-room-status", kwargs={"pk": room.id})

    # Non-staff forbidden
    c_user = APIClient(); c_user.force_authenticate(user=normal)
    r1 = c_user.patch(url, {"status": "hidden"}, format="json")
    assert r1.status_code in (403, 401), r1.data

    # Staff can hide the room
    c_staff = APIClient(); c_staff.force_authenticate(user=staff)
    r2 = c_staff.patch(url, {"status": "hidden"}, format="json")
    assert r2.status_code == 200, r2.data
    room.refresh_from_db()
    assert room.status == "hidden"

    # Staff can set back to active
    r3 = c_staff.patch(url, {"status": "active"}, format="json")
    assert r3.status_code == 200, r3.data
    room.refresh_from_db()
    assert room.status == "active"
