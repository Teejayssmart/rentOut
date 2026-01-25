import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import Room

pytestmark = pytest.mark.django_db


def assert_exact_keys(obj: dict, expected_keys: set[str]) -> None:
    assert isinstance(obj, dict), f"Expected dict, got {type(obj)}"
    assert set(obj.keys()) == expected_keys, f"Keys mismatch.\nGot: {set(obj.keys())}\nExpected: {expected_keys}"


def assert_is_bool(v, name: str) -> None:
    assert isinstance(v, bool), f"{name} must be bool, got {type(v)}"


def assert_is_int(v, name: str) -> None:
    assert isinstance(v, int), f"{name} must be int, got {type(v)}"


def make_authed_client() -> APIClient:
    """
    Preview requires authentication in your API, so use force_authenticate
    to avoid depending on login/otp in these contract tests.
    """
    User = get_user_model()
    user = User.objects.create_user(
        username="contract_preview_user",
        email="contract_preview_user@test.com",
        password="StrongP@ssword1",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def get_room_id_for_preview(client: APIClient) -> int:
    """
    In tests DB, /api/rooms/ can be empty.
    Try list first; if empty, fall back to creating a minimal Room.
    """
    r = client.get("/api/rooms/")
    assert r.status_code in (200, 401), r.data  # list might be public or auth, depending on config

    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and "id" in first:
                return int(first["id"])

    # Fallback: create a Room row directly (minimal fields only)
    # If this fails, it means Room has required fields that must be populated.
    room = Room.objects.create(
    price_per_month=1000,  # required (NOT NULL)
    )
    return int(room.id)


def test_room_preview_contract_api_and_v1_match_shape():
    client = make_authed_client()
    room_id = get_room_id_for_preview(client)

    r_api = client.get(f"/api/rooms/{room_id}/preview/")
    r_v1 = client.get(f"/api/v1/rooms/{room_id}/preview/")

    assert r_api.status_code == 200, r_api.data
    assert r_v1.status_code == 200, r_v1.data

    data_api = r_api.json()
    data_v1 = r_v1.json()

    assert isinstance(data_api, dict), f"/api preview must be dict, got {type(data_api)}"
    assert isinstance(data_v1, dict), f"/api/v1 preview must be dict, got {type(data_v1)}"

    # Contract: /api and /api/v1 preview must have identical top-level keys
    assert set(data_api.keys()) == set(data_v1.keys()), (
        f"Preview keys differ.\n/api: {sorted(data_api.keys())}\n/v1: {sorted(data_v1.keys())}"
    )

    expected_keys = set(data_api.keys())
    assert_exact_keys(data_api, expected_keys)
    assert_exact_keys(data_v1, expected_keys)

    # Minimal type locks (only if present)
    if "id" in data_api:
        assert_is_int(data_api["id"], "id")
    if "is_deleted" in data_api:
        assert_is_bool(data_api["is_deleted"], "is_deleted")
    if "is_available" in data_api:
        assert_is_bool(data_api["is_available"], "is_available")


def test_room_preview_contract_not_found_schema_is_consistent_api_and_v1():
    client = make_authed_client()
    bad_id = 999999999

    r_api = client.get(f"/api/rooms/{bad_id}/preview/")
    r_v1 = client.get(f"/api/v1/rooms/{bad_id}/preview/")

    # Because we are authenticated, not-found should NOT be 401
    assert r_api.status_code in (404, 400), r_api.data
    assert r_v1.status_code in (404, 400), r_v1.data

    data_api = r_api.json()
    data_v1 = r_v1.json()

    assert isinstance(data_api, dict), f"Error body must be dict, got {type(data_api)}"
    assert isinstance(data_v1, dict), f"Error body must be dict, got {type(data_v1)}"

    # Contract: same error key shape across /api and /api/v1
    assert set(data_api.keys()) == set(data_v1.keys()), (
        f"Error keys differ.\n/api: {set(data_api.keys())}\n/v1: {set(data_v1.keys())}"
    )