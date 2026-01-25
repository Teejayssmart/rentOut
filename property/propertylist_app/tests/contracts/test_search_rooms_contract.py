import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


# ✅ EDIT THESE TWO VALUES based on what you found in the shell output
SEARCH_PATH_API = "/api/search/rooms/"
SEARCH_PATH_V1 = "/api/v1/search/rooms/"


def make_authed_client() -> APIClient:
    """
    If your search endpoint is public, this still works.
    If it requires auth, this avoids 401/403 failures.
    """
    User = get_user_model()
    user = User.objects.create_user(
        username="contract_search_user",
        email="contract_search_user@test.com",
        password="StrongP@ssword1",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _normalise_payload(payload):
    """
    Search endpoints sometimes return:
      - list
      - dict pagination envelope (e.g. {"results": [...], ...})
    Normalise to: (envelope_type, keys_if_dict, first_item_if_list_or_results)
    """
    if isinstance(payload, list):
        first = payload[0] if payload else None
        return ("list", None, first)

    if isinstance(payload, dict):
        keys = set(payload.keys())
        # common pagination key
        if "results" in payload and isinstance(payload["results"], list):
            first = payload["results"][0] if payload["results"] else None
            return ("dict(results)", keys, first)
        return ("dict", keys, None)

    return (type(payload).__name__, None, None)


def test_search_rooms_contract_api_and_v1_match_shape():
    """
    Contract parity:
      - /api/... and /api/v1/... must return the SAME top-level type
      - if dict: same top-level keys
      - if list (or dict with results): first item key-shape must match
    """
    client = make_authed_client()

    # Use a minimal query param to reduce chances of a 400 (many search endpoints want at least something)
    params = {"q": ""}

    r_api = client.get(SEARCH_PATH_API, params)
    r_v1 = client.get(SEARCH_PATH_V1, params)

    assert r_api.status_code == 200, r_api.data
    assert r_v1.status_code == 200, r_v1.data

    data_api = r_api.json()
    data_v1 = r_v1.json()

    api_kind, api_keys, api_first = _normalise_payload(data_api)
    v1_kind, v1_keys, v1_first = _normalise_payload(data_v1)

    # Top-level envelope parity
    assert api_kind == v1_kind, f"Envelope differs: /api={api_kind}, /v1={v1_kind}"

    # Dict envelope parity (including pagination envelopes)
    if api_keys is not None:
        assert api_keys == v1_keys, f"Top-level keys differ.\n/api: {sorted(api_keys)}\n/v1: {sorted(v1_keys)}"

    # Item parity if we can compare items
    if isinstance(api_first, dict) and isinstance(v1_first, dict):
        assert set(api_first.keys()) == set(v1_first.keys()), (
            f"First item keys differ.\n/api: {sorted(api_first.keys())}\n/v1: {sorted(v1_first.keys())}"
        )