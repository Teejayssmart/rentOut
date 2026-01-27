import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

# Update these if your resolver output shows different paths
BOOKINGS_LIST_API = "/api/bookings/"
BOOKINGS_LIST_V1 = "/api/v1/bookings/"

# If your detail endpoint differs, update this pattern too
def bookings_detail_path(base: str, booking_id: int) -> str:
    return f"{base}{booking_id}/"


def make_authed_client() -> APIClient:
    """
    Force-auth avoids 401 failures and keeps these as shape/parity tests,
    not full auth-flow tests.
    """
    User = get_user_model()
    user = User.objects.create_user(
        username="contract_bookings_user",
        email="contract_bookings_user@test.com",
        password="StrongP@ssword1",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _envelope_kind(payload):
    """
    Normalise typical shapes:
      - list
      - dict
      - dict with "results" list (pagination)
    Returns: (kind, top_keys_set_or_None, first_item_dict_or_None)
    """
    if isinstance(payload, list):
        first = payload[0] if payload else None
        return ("list", None, first if isinstance(first, dict) else None)

    if isinstance(payload, dict):
        keys = set(payload.keys())
        if "results" in payload and isinstance(payload["results"], list):
            first = payload["results"][0] if payload["results"] else None
            return ("dict(results)", keys, first if isinstance(first, dict) else None)
        return ("dict", keys, None)

    return (type(payload).__name__, None, None)


def _safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return None


def assert_parity(resp_api, resp_v1):
    """
    Core contract rule:
      - status codes must match
      - if JSON dict -> key set must match
      - if list/dict(results) and has a first item dict -> key set must match
    """
    assert resp_api.status_code == resp_v1.status_code, (
        f"Status mismatch: /api={resp_api.status_code}, /v1={resp_v1.status_code}\n"
        f"/api body: {resp_api.data if hasattr(resp_api, 'data') else resp_api.content}\n"
        f"/v1 body: {resp_v1.data if hasattr(resp_v1, 'data') else resp_v1.content}"
    )

    api_json = _safe_json(resp_api)
    v1_json = _safe_json(resp_v1)

    # If non-JSON, nothing to compare beyond status
    if api_json is None or v1_json is None:
        return

    api_kind, api_keys, api_first = _envelope_kind(api_json)
    v1_kind, v1_keys, v1_first = _envelope_kind(v1_json)

    assert api_kind == v1_kind, f"Envelope mismatch: /api={api_kind}, /v1={v1_kind}"

    if api_keys is not None:
        assert api_keys == v1_keys, f"Top-level keys differ.\n/api: {sorted(api_keys)}\n/v1: {sorted(v1_keys)}"

    if api_first is not None and v1_first is not None:
        assert set(api_first.keys()) == set(v1_first.keys()), (
            f"First item keys differ.\n/api: {sorted(api_first.keys())}\n/v1: {sorted(v1_first.keys())}"
        )


def test_bookings_list_contract_api_and_v1_match_shape():
    client = make_authed_client()

    r_api = client.get(BOOKINGS_LIST_API)
    r_v1 = client.get(BOOKINGS_LIST_V1)

    assert_parity(r_api, r_v1)


def test_bookings_detail_contract_api_and_v1_match_shape_if_any_exist():
    """
    We try to derive an id from the list.
    If there are no bookings in the test DB, we skip the detail contract.
    """
    client = make_authed_client()

    r_list = client.get(BOOKINGS_LIST_API)
    if r_list.status_code != 200:
        pytest.skip(f"Bookings list not accessible (status={r_list.status_code}); skipping detail shape test.")

    data = _safe_json(r_list)
    if data is None:
        pytest.skip("Bookings list did not return JSON; skipping detail shape test.")

    kind, _, first = _envelope_kind(data)
    if kind == "list":
        booking_id = data[0]["id"] if data else None
    elif kind == "dict(results)":
        booking_id = data["results"][0]["id"] if data.get("results") else None
    else:
        booking_id = None

    if not booking_id:
        pytest.skip("No bookings exist in test DB to test detail endpoint.")

    url_api = bookings_detail_path(BOOKINGS_LIST_API, int(booking_id))
    url_v1 = bookings_detail_path(BOOKINGS_LIST_V1, int(booking_id))

    r_api = client.get(url_api)
    r_v1 = client.get(url_v1)

    assert_parity(r_api, r_v1)


def test_bookings_not_found_contract_api_and_v1_match_shape():
    """
    For a clearly invalid id, /api and /api/v1 should respond the same way (status + error shape).
    """
    client = make_authed_client()
    bad_id = 999999999

    r_api = client.get(bookings_detail_path(BOOKINGS_LIST_API, bad_id))
    r_v1 = client.get(bookings_detail_path(BOOKINGS_LIST_V1, bad_id))

    assert_parity(r_api, r_v1)