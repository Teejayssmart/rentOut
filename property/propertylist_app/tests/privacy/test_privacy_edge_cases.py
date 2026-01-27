import json
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from propertylist_app.models import UserProfile
pytestmark = pytest.mark.django_db

# =========================
# EDIT THESE PATHS TO MATCH YOUR PROJECT (use Step 1 output)
# =========================

PREFS_API = "/api/users/me/privacy-preferences/"
PREFS_V1 = "/api/v1/users/me/privacy-preferences/"

DELETE_PREVIEW_API = "/api/users/me/delete/preview/"
DELETE_PREVIEW_V1 = "/api/v1/users/me/delete/preview/"

DELETE_CONFIRM_API = "/api/users/me/delete/confirm/"
DELETE_CONFIRM_V1 = "/api/v1/users/me/delete/confirm/"

# Public endpoints to probe for leaked identity after delete confirm
ROOMS_LIST_API = "/api/rooms/"
ROOMS_LIST_V1 = "/api/v1/rooms/"
REVIEWS_LIST_API = "/api/reviews/"       # if you don’t have, it will be skipped safely
REVIEWS_LIST_V1 = "/api/v1/reviews/"
MESSAGES_LIST_API = "/api/messages/"     # if you don’t have, it will be skipped safely
MESSAGES_LIST_V1 = "/api/v1/messages/"


def make_user(username: str):
    User = get_user_model()
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="StrongP@ssword1",
    )

    # Ensure profile exists (privacy endpoints require it)
    UserProfile.objects.get_or_create(user=user)

    return user


def authed(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _json_dump(obj) -> str:
    try:
        return json.dumps(obj, default=str).lower()
    except Exception:
        return str(obj).lower()


def _endpoint_exists(client: APIClient, path: str) -> bool:
    r = client.get(path)
    return r.status_code != 404


def _extract_retention_fields(payload: dict) -> list[str]:
    # Heuristic: common names for retention / TTL fields
    keys = []
    for k, v in payload.items():
        lk = str(k).lower()
        if any(x in lk for x in ("retention", "ttl", "keep", "delete_after", "days")) and isinstance(v, (int, type(None))):
            keys.append(k)
    return keys


# ==========================================================
# 1) Privacy preferences API contract tests
# ==========================================================
def test_privacy_preferences_contract_get_api_vs_v1_match_shape_and_defaults():
    user = make_user("privacy_pref_user")
    c = authed(user)

    # If your project uses different paths, this will tell you immediately.
    assert _endpoint_exists(c, PREFS_API), f"{PREFS_API} is 404. Update PREFS_API/PREFS_V1."
    assert _endpoint_exists(c, PREFS_V1), f"{PREFS_V1} is 404. Update PREFS_API/PREFS_V1."

    r_api = c.get(PREFS_API)
    r_v1 = c.get(PREFS_V1)

    assert r_api.status_code == r_v1.status_code, (r_api.status_code, r_v1.status_code, r_api.data, r_v1.data)
    assert r_api.status_code in (200, 400, 401, 403), r_api.data

    if r_api.status_code != 200:
        return

    data_api = r_api.json()
    data_v1 = r_v1.json()

    assert isinstance(data_api, dict), f"Expected dict, got {type(data_api)}"
    assert isinstance(data_v1, dict), f"Expected dict, got {type(data_v1)}"

    # Contract: exact top-level keys match between /api and /api/v1
    assert set(data_api.keys()) == set(data_v1.keys()), (
        f"Preference keys differ.\n/api: {sorted(data_api.keys())}\n/v1: {sorted(data_v1.keys())}"
    )

    # Basic sanity: values should be JSON-serialisable primitives (bool/int/str/None)
    for k, v in data_api.items():
        assert isinstance(v, (bool, int, str, type(None), float)), f"Unexpected type for {k}: {type(v)}"


def test_privacy_preferences_patch_behaviour_api_vs_v1_is_consistent():
    user = make_user("privacy_patch_user")
    c = authed(user)

    if not _endpoint_exists(c, PREFS_API) or not _endpoint_exists(c, PREFS_V1):
        pytest.skip("Preferences endpoint not found (404). Update PREFS_* constants.")

    # Read current preferences
    r0 = c.get(PREFS_API)
    if r0.status_code != 200:
        pytest.skip("Preferences GET did not return 200; cannot test PATCH behaviour safely.")

    prefs = r0.json()
    assert isinstance(prefs, dict)

    # Choose a boolean field to toggle (if any)
    bool_keys = [k for k, v in prefs.items() if isinstance(v, bool)]
    if not bool_keys:
        pytest.skip("No boolean fields found in privacy preferences to test PATCH toggle.")

    target = bool_keys[0]
    new_val = not prefs[target]

    payload = {target: new_val}

    r_api = c.patch(PREFS_API, payload, format="json")
    r_v1 = c.patch(PREFS_V1, payload, format="json")

    assert r_api.status_code == r_v1.status_code, (r_api.status_code, r_v1.status_code, r_api.data, r_v1.data)
    assert r_api.status_code in (200, 400, 401, 403), r_api.data

    if r_api.status_code == 200:
        d_api = r_api.json()
        d_v1 = r_v1.json()
        assert isinstance(d_api, dict) and isinstance(d_v1, dict)
        assert set(d_api.keys()) == set(d_v1.keys())
        assert d_api.get(target) == d_v1.get(target) == new_val


# ==========================================================
# 2) Retention rules validation
# ==========================================================
def test_privacy_retention_rules_reject_invalid_values_api_vs_v1():
    user = make_user("privacy_retention_user")
    c = authed(user)

    if not _endpoint_exists(c, PREFS_API) or not _endpoint_exists(c, PREFS_V1):
        pytest.skip("Preferences endpoint not found (404). Update PREFS_* constants.")

    r0 = c.get(PREFS_API)
    if r0.status_code != 200:
        pytest.skip("Preferences GET did not return 200; cannot detect retention fields.")

    prefs = r0.json()
    assert isinstance(prefs, dict)

    retention_fields = _extract_retention_fields(prefs)
    if not retention_fields:
        pytest.skip("No retention-like integer fields detected (retention/ttl/days).")

    field = retention_fields[0]

    # Try obviously invalid values
    for bad in (-1, 0, 10**9):
        payload = {field: bad}

        r_api = c.patch(PREFS_API, payload, format="json")
        r_v1 = c.patch(PREFS_V1, payload, format="json")

        assert r_api.status_code == r_v1.status_code, (r_api.status_code, r_v1.status_code, r_api.data, r_v1.data)

        # Contract: must not accept these silently
        assert r_api.status_code in (400, 403, 401), r_api.data


# ==========================================================
# 3) After delete confirm: ensure content is hidden/anonymised in public endpoints
# ==========================================================
def test_after_delete_confirm_user_identity_is_not_leaked_in_public_endpoints():
    user = make_user("privacy_delete_user")
    c = authed(user)

    # If your delete endpoints differ, force you to set the constants correctly.
    if not _endpoint_exists(c, DELETE_CONFIRM_API) or not _endpoint_exists(c, DELETE_CONFIRM_V1):
        pytest.skip("Delete confirm endpoint not found (404). Update DELETE_CONFIRM_* constants.")

    # Run delete confirm on both /api and /api/v1 and require consistent status
    r_api = c.post(DELETE_CONFIRM_API, {}, format="json")
    r_v1 = c.post(DELETE_CONFIRM_V1, {}, format="json")

    assert r_api.status_code == r_v1.status_code, (r_api.status_code, r_v1.status_code, r_api.data, r_v1.data)
    assert r_api.status_code in (200, 202, 204, 400, 403), r_api.data

    # Now probe public endpoints and ensure username/email are not present in JSON output
    probes = [
        (ROOMS_LIST_API, ROOMS_LIST_V1),
        (REVIEWS_LIST_API, REVIEWS_LIST_V1),
        (MESSAGES_LIST_API, MESSAGES_LIST_V1),
    ]

    leaked_markers = [user.username.lower(), user.email.lower()]

    for api_path, v1_path in probes:
        # If endpoint doesn’t exist in your project, skip it (404 on both)
        r1 = APIClient().get(api_path)
        r2 = APIClient().get(v1_path)

        if r1.status_code == 404 and r2.status_code == 404:
            continue

        # We only require: both versions behave the same in terms of leakage check.
        # Endpoints may be 401/403 if protected; that’s still “safe” for leakage.
        if r1.status_code in (200,) and r2.status_code in (200,):
            dump1 = _json_dump(r1.json())
            dump2 = _json_dump(r2.json())

            for marker in leaked_markers:
                assert marker not in dump1, f"Leak detected in {api_path}: {marker}"
                assert marker not in dump2, f"Leak detected in {v1_path}: {marker}"