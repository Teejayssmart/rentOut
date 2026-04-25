import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


# -----------------------------
# CANONICAL V1 ENDPOINT ONLY
# -----------------------------
SEARCH_PATH_V1 = "/api/v1/search/rooms/"


def make_authed_client() -> APIClient:
    """
    Reason: Some search endpoints are protected in this project.
    We force-auth to avoid 401/403 breaking contract tests.
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
    Search endpoints may return:
      - list
      - dict pagination envelope (e.g. {"results": [...], ...})
      - ok envelope {"ok": True, "data": <list|dict>}
    Normalise to: (kind, keys_if_dict, first_item_if_list_or_results)
    """
    # ok envelope
    if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
        payload = payload["data"]

    if isinstance(payload, list):
        first = payload[0] if payload else None
        return ("list", None, first)

    if isinstance(payload, dict):
        keys = set(payload.keys())
        if "results" in payload and isinstance(payload["results"], list):
            first = payload["results"][0] if payload["results"] else None
            return ("dict(results)", keys, first)
        return ("dict", keys, None)

    return (type(payload).__name__, None, None)


def test_search_rooms_contract_v1_shape_is_stable():
    """
    V1 contract:
      - status 200
      - payload is either list or dict (including pagination dict)
      - if list/results has at least one item, that item is a dict
    Note: we do NOT enforce a fixed keyset here because search payloads
    can legitimately evolve (filters/additions). This locks shape only.
    """
    client = make_authed_client()

    # Minimal params to avoid validation errors.
    # If your endpoint requires something non-empty, change this one line only.
    params = {"q": ""}

    r = client.get(SEARCH_PATH_V1, params)
    assert r.status_code == 200, getattr(r, "content", b"")

    data = r.json()
    kind, keys, first = _normalise_payload(data)

    assert kind in ("list", "dict", "dict(results)"), f"Unexpected payload type: {kind}"

    # If it’s a dict, keys must exist
    if keys is not None:
        assert isinstance(keys, set) and keys, "Dict payload must have keys."

    # If we have a first item to inspect, it must be a dict
    if first is not None:
        assert isinstance(first, dict), f"First item must be dict, got {type(first)}"
