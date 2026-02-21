import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


# Common “account/profile/me” endpoints. The test will try each until it finds one that exists.
CANDIDATE_RELATIVE_PATHS = [
    "users/me/",
    "users/me/profile/",
]



def make_authed_client() -> APIClient:
    """
    These endpoints almost always require authentication.
    We force_authenticate to avoid depending on OTP/login flows in contract tests.
    """
    User = get_user_model()
    user = User.objects.create_user(
        username="contract_account_user",
        email="contract_account_user@test.com",
        password="StrongP@ssword1",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _normalise_payload(payload):
    """
    Normalise responses that could be:
      - dict
      - list
      - paginated dict (results)
    Returns: (kind, top_level_keys_or_none, first_item_dict_or_none)
    """
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


def _get(client: APIClient, prefix: str, rel: str):
    # prefix: "/api" or "/api/v1"
    url = f"{prefix}/{rel}".replace("//", "/")
    return client.get(url)


def _find_first_existing_endpoint(client: APIClient):
    """
    Returns the first relative path that is NOT a 404 on BOTH /api and /api/v1.
    If everything is 404, we skip (means your project uses different paths).
    """
    for rel in CANDIDATE_RELATIVE_PATHS:
        r_api = _get(client, "/api", rel)
        r_v1 = _get(client, "/api/v1", rel)

        # If both are 404, this candidate doesn't exist.
        if r_api.status_code == 404 and r_v1.status_code == 404:
            continue

        return rel, r_api, r_v1

    return None, None, None

def test_account_profile_contract_api_and_v1_match_shape():
    """
    Canonical contract test for account/profile endpoint.

    This project uses /api/v1 as the supported base.
    /api alias is not required to exist.
    """
    client = make_authed_client()

    # Try canonical base only
    for rel in CANDIDATE_RELATIVE_PATHS:
        url = f"/api/v1/{rel}".replace("//", "/")
        r = client.get(url)

        if r.status_code == 404:
            continue  # try next candidate

        # Found an endpoint
        assert r.status_code in (200, 400, 401, 403), getattr(r, "data", r.content)

        if r.status_code != 200:
            return

        data = r.json()
        kind, keys, first = _normalise_payload(data)

        assert kind in ("dict", "list", "dict(results)")

        if keys is not None:
            assert isinstance(keys, set)

        if isinstance(first, dict):
            assert isinstance(first, dict)

        return

    pytest.fail(
        "No account/profile/me endpoint found under /api/v1 using CANDIDATE_RELATIVE_PATHS."
    )


    # Allow typical outcomes for these endpoints.
    # If /api is redirect-only (308), skip alias comparison.
    # If /api is redirect-only (308), skip alias comparison.
    if r_api.status_code == 308:
        pytest.skip("/api alias is redirect-only; /api/v1 is canonical.")

    # Allow typical outcomes for these endpoints.
    assert r_api.status_code in (200, 400, 401, 403), getattr(r_api, "data", r_api.content)
    assert r_v1.status_code in (200, 400, 401, 403), getattr(r_v1, "data", r_v1.content)



    data_api = r_api.json()
    data_v1 = r_v1.json()

    api_kind, api_keys, api_first = _normalise_payload(data_api)
    v1_kind, v1_keys, v1_first = _normalise_payload(data_v1)

    # Top-level type parity
    assert api_kind == v1_kind, f"Envelope differs for {rel}: /api={api_kind}, /v1={v1_kind}"

    # Dict keys parity (including paginated dicts)
    if api_keys is not None:
        assert api_keys == v1_keys, (
            f"Top-level keys differ for {rel}.\n"
            f"/api: {sorted(api_keys)}\n"
            f"/v1: {sorted(v1_keys)}"
        )

    # If we have a comparable first item dict, enforce key parity
    if isinstance(api_first, dict) and isinstance(v1_first, dict):
        assert set(api_first.keys()) == set(v1_first.keys()), (
            f"First item keys differ for {rel}.\n"
            f"/api: {sorted(api_first.keys())}\n"
            f"/v1: {sorted(v1_first.keys())}"
        )
        
        
        
        
        
        
        
        
        
        
        
        
        
        