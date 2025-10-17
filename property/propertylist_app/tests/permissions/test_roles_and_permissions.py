import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from propertylist_app.models import RoomCategorie, Room, Report

User = get_user_model()


@pytest.mark.django_db
def test_staff_can_access_moderation_and_ops_endpoints_regular_user_cannot():
    # users
    user = User.objects.create_user(username="u1", password="pass123", email="u1@example.com")
    staff = User.objects.create_user(username="admin", password="pass123", email="a@example.com", is_staff=True)

    # data needed for moderation endpoints
    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="Test room", description="...", price_per_month=900, location="London",
        category=cat, property_owner=user
    )

    # add content type for Room model
    ct = ContentType.objects.get_for_model(Room)
    report = Report.objects.create(
        reporter=user,
        target_type="room",
        content_type=ct,
        object_id=room.id,
        reason="abuse",
        details="",
    )

    # NOTE: report.content_type is set by API serializer in real calls; for list/update we only need an existing report row.
    c = APIClient()

    # --- regular user blocked ---
    c.force_authenticate(user=user)
    r1 = c.get(reverse("v1:moderation-report-list"))
    r2 = c.patch(reverse("v1:moderation-report-update", kwargs={"pk": report.pk}), {"status": "in_review"}, format="json")
    r3 = c.patch(reverse("v1:moderation-room-status", kwargs={"pk": room.pk}), {"status": "hidden"}, format="json")
    r4 = c.get(reverse("v1:ops-stats"))

    assert r1.status_code == 403
    assert r2.status_code == 403
    assert r3.status_code == 403
    assert r4.status_code == 403

    # --- staff allowed ---
    c.force_authenticate(user=staff)
    r1s = c.get(reverse("v1:moderation-report-list"))
    r2s = c.patch(reverse("v1:moderation-report-update", kwargs={"pk": report.pk}), {"status": "in_review"}, format="json")
    r3s = c.patch(reverse("v1:moderation-room-status", kwargs={"pk": room.pk}), {"status": "hidden"}, format="json")
    r4s = c.get(reverse("v1:ops-stats"))

    assert r1s.status_code == 200
    assert r2s.status_code in (200, 202, 204)  # update returns body in our API, so 200 expected
    assert r3s.status_code == 200
    assert r4s.status_code == 200


@pytest.mark.django_db
def test_notifications_are_user_only_and_isolated_per_user():
    u1 = User.objects.create_user(username="alice", password="pass123", email="a@example.com")
    u2 = User.objects.create_user(username="bob", password="pass123", email="b@example.com")

    # Create a notification for u1 only (the system does this via signals normally)
    from propertylist_app.models import Notification
    Notification.objects.create(user=u1, title="Hello", body="Only for Alice")

    c = APIClient()

    # u2 should NOT see u1's notification
    c.force_authenticate(user=u2)
    r_u2 = c.get(reverse("v1:notifications-list"))
    assert r_u2.status_code == 200
    assert r_u2.json() == []

    # u1 sees their own notification
    c.force_authenticate(user=u1)
    r_u1 = c.get(reverse("v1:notifications-list"))
    assert r_u1.status_code == 200
    items = r_u1.json()
    assert len(items) == 1
    assert items[0]["title"] == "Hello"
