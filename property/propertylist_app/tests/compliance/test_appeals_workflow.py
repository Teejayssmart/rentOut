import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import RoomCategorie, Room, Report
from django.contrib.contenttypes.models import ContentType

User = get_user_model()


@pytest.mark.django_db
def test_owner_can_file_appeal_report_for_hidden_room_and_staff_can_unhide_and_resolve():
    """
    Flow:
    - Owner has a room that is currently HIDDEN.
    - Owner files an 'appeal' via POST /api/reports/ (we use your existing ReportCreateView).
    - Room does NOT auto-unhide.
    - Staff reviews: (a) set room status ACTIVE, (b) resolve the report.
    - Room is now active again.
    """
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
    staff = User.objects.create_user(username="mod", password="pass123", email="m@example.com", is_staff=True)
    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="Hidden Room",
        description="..",
        price_per_month=700,
        location="London",
        category=cat,
        property_owner=owner,
        status="hidden",   # ← already hidden (e.g., by moderation or expiry)
    )

    c = APIClient()

    # Owner files an "appeal" using the generic /reports/ endpoint
    c.force_authenticate(user=owner)
    r_create = c.post(
        reverse("v1:report-create"),
        {
            "target_type": "room",
            "object_id": room.id,
            "reason": "appeal",
            "details": "Please unhide my listing; issue resolved.",
        },
        format="json",
    )
    assert r_create.status_code == 201, r_create.data
    appeal_id = r_create.data["id"]
    appeal = Report.objects.get(pk=appeal_id)
    assert appeal.status == "open"
    assert appeal.target_type == "room"
    assert appeal.object_id == room.id

    # Appeal creation does NOT auto-unhide the room
    room.refresh_from_db()
    assert room.status == "hidden"

    # Staff performs moderation: unhide the room and resolve the appeal
    c.force_authenticate(user=staff)

    # 1) Unhide via the existing moderation endpoint
    r_status = c.patch(
        reverse("v1:moderation-room-status", kwargs={"pk": room.pk}),
        {"status": "active"},
        format="json",
    )
    assert r_status.status_code == 200, r_status.data
    room.refresh_from_db()
    assert room.status == "active"

    # 2) Resolve the appeal report
    r_update = c.patch(
        reverse("v1:moderation-report-update", kwargs={"pk": appeal_id}),
        {"status": "resolved", "resolution_notes": "Reviewed & reinstated."},
        format="json",
    )
    assert r_update.status_code in (200, 202, 204), r_update.data
    appeal.refresh_from_db()
    assert appeal.status == "resolved"


@pytest.mark.django_db
def test_appeal_does_not_auto_unhide_without_staff_action():
    """
    Ensure that merely creating an appeal report DOES NOT change the room visibility.
    (Guards against silent policy regressions.)
    """
    owner = User.objects.create_user(username="u", password="x")
    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="Still Hidden",
        description="..",
        price_per_month=600,
        location="Leeds",
        category=cat,
        property_owner=owner,
        status="hidden",
    )

    c = APIClient()
    c.force_authenticate(user=owner)
    r = c.post(
        reverse("v1:report-create"),
        {"target_type": "room", "object_id": room.id, "reason": "appeal", "details": "…"},
        format="json",
    )
    assert r.status_code == 201, r.data

    room.refresh_from_db()
    assert room.status == "hidden"  # unchanged


@pytest.mark.django_db
@pytest.mark.xfail(reason="Nice-to-have policy guard not implemented yet.")
def test_cannot_file_appeal_for_active_room():
    """
    Optional policy we recommend: block appeals for rooms that are already ACTIVE.
    (Marking xfail until you decide to enforce this rule in ReportCreateView/serializer.)
    """
    owner = User.objects.create_user(username="o2", password="x")
    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="Already Active",
        description="..",
        price_per_month=650,
        location="Birmingham",
        category=cat,
        property_owner=owner,
        status="active",
    )

    c = APIClient()
    c.force_authenticate(user=owner)
    r = c.post(
        reverse("v1:report-create"),
        {"target_type": "room", "object_id": room.id, "reason": "appeal", "details": "…"},
        format="json",
    )
    # Desired behavior once enforced:
    assert r.status_code == 400
