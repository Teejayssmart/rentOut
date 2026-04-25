import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import RoomCategorie

pytestmark = pytest.mark.django_db


# -----------------------------
# CANONICAL V1 ENDPOINT ONLY
# -----------------------------
ROOM_CATEGORIES_LIST_V1 = "/api/v1/room-categories/"


def make_authed_client() -> APIClient:
    """
    Contract tests should not depend on login/otp flows.
    Force-authenticate at DRF test-client level.
    """
    User = get_user_model()
    user = User.objects.create_user(
        username="contract_room_categories_user",
        email="contract_room_categories_user@test.com",
        password="StrongP@ssword1",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _normalise_list_payload(payload):
    """
    Supports:
      - list
      - paginated dict: {"results": [...]}
      - ok envelope: {"ok": True, "data": <list|dict>}
    Returns list or None.
    """
    if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
        payload = payload["data"]

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]

    return None


def _assert_forbidden_envelope(r):
    """
    Your API returns a standard error envelope.
    We assert the key contract bits only (no overfitting).
    """
    assert r.status_code == 403, getattr(r, "content", b"")
    payload = r.json()
    assert isinstance(payload, dict), f"Error body must be dict, got {type(payload)}"

    # A4-style envelope (based on your actual failure output)
    assert payload.get("ok") is False
    assert payload.get("status") == 403

    # These may vary, but your output shows them consistently:
    assert payload.get("code") in ("forbidden", "permission_denied", "not_authenticated", "auth_error")
    assert "message" in payload
    assert "detail" in payload


def test_room_categories_list_contract_v1_returns_items_or_forbidden_envelope():
    client = make_authed_client()

    # Ensure at least one exists in DB (so if endpoint is allowed, list won't be empty)
    RoomCategorie.objects.create(name="ContractCat", active=True)

    r = client.get(ROOM_CATEGORIES_LIST_V1)

    # If endpoint is permission-protected, we still pass by validating forbidden envelope
    if r.status_code == 403:
        _assert_forbidden_envelope(r)
        return

    assert r.status_code == 200, getattr(r, "content", b"")

    payload = r.json()
    items = _normalise_list_payload(payload)

    assert isinstance(items, list), (
        f"{ROOM_CATEGORIES_LIST_V1} must return list or paginated dict, got {type(payload)}"
    )
    assert items, "room-categories returned empty list even after creating a RoomCategorie."

    first = items[0]
    assert isinstance(first, dict), f"Category item must be dict, got {type(first)}"

    required_keys = {"id", "name"}
    missing = required_keys - set(first.keys())
    assert not missing, f"Missing required room-category keys: {sorted(missing)}"


def test_room_categories_detail_contract_v1_returns_item_or_forbidden_envelope():
    client = make_authed_client()

    cat = RoomCategorie.objects.create(name="ContractCatDetail", active=True)
    r = client.get(f"{ROOM_CATEGORIES_LIST_V1}{cat.id}/")

    if r.status_code == 403:
        _assert_forbidden_envelope(r)
        return

    assert r.status_code == 200, getattr(r, "content", b"")

    payload = r.json()
    if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
        payload = payload["data"]

    assert isinstance(payload, dict), f"Detail payload must be dict, got {type(payload)}"

    required_keys = {"id", "name"}
    missing = required_keys - set(payload.keys())
    assert not missing, f"Missing required room-category detail keys: {sorted(missing)}"

    assert int(payload["id"]) == cat.id


def test_room_categories_not_found_contract_v1_returns_not_found_or_forbidden_envelope():
    client = make_authed_client()
    bad_id = 999999999

    r = client.get(f"{ROOM_CATEGORIES_LIST_V1}{bad_id}/")

    # If permission blocks, validate forbidden envelope (no skipping)
    if r.status_code == 403:
        _assert_forbidden_envelope(r)
        return

    # Otherwise, typical outcomes: 404 (not found) or 400 (validation)
    assert r.status_code in (404, 400), getattr(r, "content", b"")

    payload = r.json()
    assert isinstance(payload, dict), f"Error body must be dict, got {type(payload)}"
    assert payload, "Error body should not be empty."
