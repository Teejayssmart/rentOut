import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def make_authed_client() -> APIClient:
    """
    Contract tests should not depend on login/otp flows.
    This logs in the request at the DRF test-client level.
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
      - dict envelope: {"results": [{id: ...}, ...], ...}
    Returns int id or None.
    """
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict) and "id" in first:
            return int(first["id"])

    if isinstance(payload, dict) and "results" in payload and isinstance(payload["results"], list) and payload["results"]:
        first = payload["results"][0]
        if isinstance(first, dict) and "id" in first:
            return int(first["id"])

    return None


def _assert_error_parity(r_api, r_v1):
    assert r_api.status_code == r_v1.status_code, (
        f"Status differs.\n/api: {r_api.status_code} {r_api.data}\n/v1: {r_v1.status_code} {r_v1.data}"
    )
    data_api = r_api.json()
    data_v1 = r_v1.json()
    assert isinstance(data_api, dict) and isinstance(data_v1, dict), "Error body must be dict on both endpoints."
    assert set(data_api.keys()) == set(data_v1.keys()), (
        f"Error keys differ.\n/api: {set(data_api.keys())}\n/v1: {set(data_v1.keys())}"
    )


def test_booking_reviews_list_contract_api_and_v1_match_shape_if_any_exist():
    """
    Contract parity for:
      GET /bookings/<id>/reviews/

    If there are no bookings in the test DB, we skip.
    If permission blocks access (403), we only enforce parity.
    """
    client = make_authed_client()

    # Find a booking id from list endpoint
    r_list = client.get("/api/bookings/")
    assert r_list.status_code in (200, 401, 403), r_list.data

    if r_list.status_code != 200:
        # If even listing bookings is blocked, nothing useful to contract here.
        pytest.skip(f"Bookings list is not accessible in tests (status {r_list.status_code}).")

    booking_id = _extract_first_id(r_list.json())
    if not booking_id:
        pytest.skip("No bookings exist in test DB to test booking reviews list endpoint.")

    r_api = client.get(f"/api/bookings/{booking_id}/reviews/")
    r_v1 = client.get(f"/api/v1/bookings/{booking_id}/reviews/")

    # If not 200, enforce parity of error response
    if r_api.status_code != 200 or r_v1.status_code != 200:
        _assert_error_parity(r_api, r_v1)
        return

    data_api = r_api.json()
    data_v1 = r_v1.json()

    # Both should be same top-level type
    assert type(data_api) is type(data_v1), f"Payload type differs: /api={type(data_api)}, /v1={type(data_v1)}"

    # If lists, compare first item keys (if any)
    if isinstance(data_api, list):
        if not data_api and not data_v1:
            return
        assert isinstance(data_api[0], dict) and isinstance(data_v1[0], dict)
        assert set(data_api[0].keys()) == set(data_v1[0].keys())
        return

    # If dict, compare top-level keys
    if isinstance(data_api, dict):
        assert set(data_api.keys()) == set(data_v1.keys())
        return

    pytest.fail(f"Unexpected payload type: {type(data_api)}")


def test_booking_reviews_not_found_contract_api_and_v1_match_shape():
    """
    Contract parity for not-found:
      GET /bookings/<bad_id>/reviews/

    We do NOT force 404 specifically because permission may produce 403.
    We only require /api and /api/v1 to match.
    """
    client = make_authed_client()
    bad_id = 999999999

    r_api = client.get(f"/api/bookings/{bad_id}/reviews/")
    r_v1 = client.get(f"/api/v1/bookings/{bad_id}/reviews/")

    _assert_error_parity(r_api, r_v1)


def test_booking_reviews_create_not_found_contract_api_and_v1_match_shape():
    """
    Contract parity for:
      POST /bookings/<bad_id>/reviews/create/

    We send an empty payload because we only care about the top-level error shape parity.
    """
    client = make_authed_client()
    bad_id = 999999999

    r_api = client.post(f"/api/bookings/{bad_id}/reviews/create/", data={}, format="json")
    r_v1 = client.post(f"/api/v1/bookings/{bad_id}/reviews/create/", data={}, format="json")

    _assert_error_parity(r_api, r_v1)