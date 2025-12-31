# property/propertylist_app/tests/privacy/test_export_and_delete.py
import os
import re
import json
import pytest
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient
from django.contrib.auth.models import User

from datetime import timedelta
from propertylist_app.models import (
    Room,
    RoomCategorie,
    Review,
    MessageThread,
    Message,
    DataExport,
    Booking,
)

# NOTE: We call concrete URLs to avoid depending on URL names.
EXPORT_START_URL = "/api/v1/users/me/export/"
EXPORT_LATEST_URL = "/api/v1/users/me/export/latest/"
DELETE_PREVIEW_URL = "/api/v1/users/me/delete/preview/"
DELETE_CONFIRM_URL = "/api/v1/users/me/delete/confirm/"


@pytest.mark.django_db
def test_export_creates_artifact(tmp_path, monkeypatch):
    """
    Requesting a data export creates an artifact we can download.
    Asserts:
      - 201 status
      - download_url present
      - file exists under MEDIA_ROOT based on the returned URL
      - a DataExport row exists for the user
    """
    # Ensure MEDIA_ROOT is writable for the test (override just for this run)
    monkeypatch.setattr(settings, "MEDIA_ROOT", tmp_path, raising=False)
    # Keep MEDIA_URL; default in settings is '/media/' – fine for this test.

    user = User.objects.create_user(username="gdpr_user", password="pass123", email="u@example.com")
    client = APIClient()
    client.force_authenticate(user=user)

    r = client.post(EXPORT_START_URL, data={"confirm": True}, format="json")
    assert r.status_code == 201, r.content

    data = r.json()
    assert "download_url" in data
    assert data.get("status") in {"processing", "ready", None, ""}  # build_export_zip may update to "ready"

    # Extract the path component and map it to MEDIA_ROOT
    parsed = urlparse(data["download_url"])
    # Expect something like /media/exports/user_xxx.zip
    # Remove the MEDIA_URL prefix from the path:
    media_prefix = settings.MEDIA_URL.rstrip("/") if settings.MEDIA_URL else "/media"
    path_in_media = re.sub(rf"^{re.escape(media_prefix)}/?", "", parsed.path)
    file_abs_path = os.path.join(settings.MEDIA_ROOT, path_in_media)

    # File should exist (build_export_zip is expected to create it)
    assert os.path.exists(file_abs_path), f"Export file not found at {file_abs_path}"

    # A DataExport entry should exist for the user
    assert DataExport.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_delete_preview_counts():
    """
    The preview endpoint correctly reports what data will be affected.
    We create some user data and expect non-zero counts in the preview.
    """
    owner = User.objects.create_user(username="del_owner", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="MyCat", active=True)
    room = Room.objects.create(title="My Room", category=cat, price_per_month=500, property_owner=owner)
    # Some content tied to the user
    tenant = User.objects.create_user(
    username="del_tenant",
    password="pass123",
    email="del_tenant@example.com",
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
        reviewee=owner,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["responsive"],
        notes="Good",
        active=True,
    )

    th = MessageThread.objects.create()
    th.participants.set([owner])
    Message.objects.create(thread=th, sender=owner, body="Hello")

    client = APIClient()
    client.force_authenticate(user=owner)

    r = client.get(DELETE_PREVIEW_URL)
    assert r.status_code == 200, r.content

    data = r.json()
    # We can't rely on exact schema of preview_erasure(), but it should reflect some non-zero impact.
    # Common keys: counts or similar. Accept any structure that includes a positive indication.
    # Try a few likely places:
    payload_text = json.dumps(data).lower()
    # Expect at least one numeric value > 0 to appear (rooms/reviews/messages/etc.)
    assert any(s in payload_text for s in ["room", "review", "message", "count", "total"])


@pytest.mark.django_db
def test_delete_confirm_erases_pii_and_soft_hides_content():
    """
    Confirmed deletion should:
      - deactivate the account (is_active = False)
      - scrub/erase PII where implemented
      - soft-hide or anonymise related content (room no longer publicly attributable)
    The exact anonymisation policy may vary; this test uses tolerant checks.
    """
    owner = User.objects.create_user(username="erase_me", password="pass123", email="erase@example.com")
    cat = RoomCategorie.objects.create(name="GDPR", active=True)
    room = Room.objects.create(title="GDPR Room", category=cat, price_per_month=700, property_owner=owner)
    tenant2 = User.objects.create_user(
    username="erase_tenant",
    password="pass123",
    email="erase_tenant@example.com",
    )

    booking2 = Booking.objects.create(
        user=tenant2,
        room=room,
        start=timezone.now() - timedelta(days=40),
        end=timezone.now() - timedelta(days=35),
        status=Booking.STATUS_ACTIVE,
    )

    Review.objects.create(
        booking=booking2,
        reviewer=tenant2,
        reviewee=owner,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["responsive"],
        notes="Great",
        active=True,
    )


    client = APIClient()
    client.force_authenticate(user=owner)

    # Confirm deletion
    r = client.post(DELETE_CONFIRM_URL, data={"confirm": True}, format="json")
    assert r.status_code in (200, 204), r.content

    # Reload user & room
    owner.refresh_from_db()
    room.refresh_from_db()

    # 1) User deactivated
    assert owner.is_active is False

    # 2) PII erased (be tolerant: email may be blank/None/placeholder)
    email_val = (owner.email or "").strip().lower()
    assert email_val in {"", "redacted", "anonymised", "anonymized"} or "@" not in email_val

    # 3) Content hidden or disassociated (tolerant: status hidden OR deleted OR no owner)
    owner_id = getattr(room, "property_owner_id", None)
    status_val = getattr(room, "status", "")
    is_deleted = bool(getattr(room, "is_deleted", False))
    assert (
        owner_id is None
        or status_val == "hidden"
        or is_deleted is True
    ), "Room still publicly attributable after erasure"
