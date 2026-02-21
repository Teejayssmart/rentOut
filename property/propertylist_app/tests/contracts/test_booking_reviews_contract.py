import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def make_authed_client() -> APIClient:
    """
    Contract tests should not depend on login/otp flows.
    Force-authenticate a user at the DRF test-client level.
    """
    User = get_user_model()
    user = User.objects.create_user(
        username="contract_booking_reviews_user",
        email="contract_booking_reviews_user@test.com",
        password="StrongP@ssword1",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client

def _extract_first_id(payload):
    """
    Supports both:
      - list: [{id: ...}, ...]
      - dict with results: {"results": [{id: ...}, ...], ...}
      - ok envelope: {"ok": True, "data": <list|dict>}
    Returns int id or None.
    """
    # unwrap success envelope if present
    if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
        payload = payload["data"]

    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict) and "id" in first:
            return int(first["id"])

    if (
        isinstance(payload, dict)
        and "results" in payload
        and isinstance(payload["results"], list)
        and payload["results"]
    ):
        first = payload["results"][0]
        if isinstance(first, dict) and "id" in first:
            return int(first["id"])

    return None


def _assert_error_envelope(resp):
    """
    Your API error contract uses a consistent dict body.
    We do NOT hard-code exact keys here, we only assert it's a dict.
    """
    assert resp.status_code in (400, 401, 403, 404, 409, 429), getattr(resp, "content", b"")
    data = resp.json()
    assert isinstance(data, dict), f"Error body must be a dict, got {type(data)}"


def _assert_success_shape_parity(data):
    """
    For success payloads:
    - if list: items should be dicts (if any)
    - if dict: must be dict
    """
    if isinstance(data, list):
        if not data:
            return
        assert isinstance(data[0], dict), f"Expected list items to be dict, got {type(data[0])}"
        return

    if isinstance(data, dict):
        return

    pytest.fail(f"Unexpected payload type: {type(data)}")


def test_booking_reviews_list_contract_v1_if_any_exist():
    """
    Contract for:
      GET /api/v1/bookings/<id>/reviews/

    Now self-contained: creates a booking so it never skips.
    """
    from propertylist_app.models import Room, Booking, RoomCategorie
    from django.utils import timezone
    from datetime import timedelta

    client = make_authed_client()
    user = client.handler._force_user

    # Create minimal booking
    cat = RoomCategorie.objects.create(name="ContractCat")
    room = Room.objects.create(
        title="Contract Room",
        description=(
        "This is a contract test room description written to satisfy the minimum word "
        "requirement in the Room model. It contains more than twenty five words for validation."
            ),
        price_per_month=500,
        location="Test",
        category=cat,
        property_owner=user,
    )

    booking = Booking.objects.create(
        user=user,
        room=room,
        start=timezone.now() - timedelta(days=2),
        end=timezone.now() - timedelta(days=1),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )

    r = client.get(f"/api/v1/bookings/{booking.id}/reviews/")

    if r.status_code != 200:
        _assert_error_envelope(r)
        return

    data = r.json()
    _assert_success_shape_parity(data)


def test_booking_reviews_not_found_contract_v1():
    """
    Contract for not-found:
      GET /api/v1/bookings/<bad_id>/reviews/

    We accept 404 (not found) or 403 (permission).
    """
    client = make_authed_client()
    bad_id = 999999999

    r = client.get(f"/api/v1/bookings/{bad_id}/reviews/")

    if r.status_code == 200:
        # If your system returns 200 here, it's unexpected — force visibility
        pytest.fail("Expected not-found/permission error, got 200.")
    _assert_error_envelope(r)


def test_booking_reviews_create_not_found_contract_v1():
    """
    Contract parity for:
      POST /api/v1/bookings/<bad_id>/reviews/create/

    We send empty payload because we only care about top-level error envelope.
    """
    client = make_authed_client()
    bad_id = 999999999

    r = client.post(f"/api/v1/bookings/{bad_id}/reviews/create/", data={}, format="json")

    if r.status_code == 200:
        pytest.fail("Expected not-found/permission error, got 200.")
    _assert_error_envelope(r)
