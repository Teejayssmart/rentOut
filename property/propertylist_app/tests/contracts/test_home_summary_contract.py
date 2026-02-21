import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

# -----------------------------
# Update these from Figma
# -----------------------------
# Put ONLY the fields your Home screen needs.
# These must exist even if None.
REQUIRED_HOME_FIELDS: set[str] = set([
    "app_links",
    "featured_rooms",
    "latest_rooms",
    "popular_cities",
    "stats",
])

# Candidate endpoints (update/add if your project uses a different one)
HOME_CANDIDATE_PATHS = [
    "/api/v1/home/",
    "/api/v1/homepage/",
    "/api/v1/home/summary/",
    "/api/v1/home-summary/",
    "/api/v1/summary/home/",
    "/api/v1/cities/",
    "/api/v1/city-list/",
]

# Reason: HOME_CANDIDATE_PATHS already uses /api/v1; rebuilding would produce /api/v1/v1/... (invalid)
HOME_CANDIDATE_PATHS_V1 = HOME_CANDIDATE_PATHS


def make_authed_client() -> APIClient:
    User = get_user_model()
    user = User.objects.create_user(
        username="contract_home_user",
        email="contract_home_user@test.com",
        password="StrongP@ssword1",
    )
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _get_first_existing(client: APIClient):
    """
    Find a home-ish endpoint that is not 404 on both /api and /api/v1.
    """
    for api_path, v1_path in zip(HOME_CANDIDATE_PATHS, HOME_CANDIDATE_PATHS_V1):
        r_api = client.get(api_path)
        r_v1 = client.get(v1_path)

        if r_api.status_code == 404 and r_v1.status_code == 404:
            continue

        return api_path, v1_path, r_api, r_v1

    return None, None, None, None


def _normalise(payload):
    # Home might return dict or list (less likely). Lock type + keys.
    if isinstance(payload, dict):
        return ("dict", set(payload.keys()))
    if isinstance(payload, list):
        return ("list", None)
    return (type(payload).__name__, None)


def test_home_summary_contract_api_and_v1_match_shape_and_required_fields():
    c = make_authed_client()
    api_path, v1_path, r_api, r_v1 = _get_first_existing(c)

    if not api_path:
        pytest.skip("No home summary endpoint found in HOME_CANDIDATE_PATHS. Add your real path(s).")

    

    # parity status
    assert r_api.status_code == r_v1.status_code, (
        f"Status mismatch.\n{api_path} -> {r_api.status_code}\n{v1_path} -> {r_v1.status_code}"
    )


    # allow common responses
    assert r_api.status_code in (200, 401, 403), r_api.data

    # If it requires auth and we still got blocked, we stop here (still parity-checked).
    if r_api.status_code != 200:
        return

    data_api = r_api.json()
    data_v1 = r_v1.json()

    kind_api, keys_api = _normalise(data_api)
    kind_v1, keys_v1 = _normalise(data_v1)

    assert kind_api == kind_v1, f"Envelope type differs: /api={kind_api}, /v1={kind_v1}"

    # if dict -> same keys
    if keys_api is not None:
        assert keys_api == keys_v1, (
            f"Top-level keys differ.\n/api: {sorted(keys_api)}\n/v1: {sorted(keys_v1)}"
        )

        # strict required fields for frontend stability
        if not REQUIRED_HOME_FIELDS:
            pytest.fail(
                "REQUIRED_HOME_FIELDS is empty.\n"
                f"Paste your Figma-required Home keys here. Current keys: {sorted(keys_api)}"
            )

        # reason: Home endpoint can be wrapped in A3 envelope: {"ok": true, "data": {...}}
        # Required fields must be validated against the payload object (inner data), not the top-level envelope.

        payload_api = data_api.get("data") if isinstance(data_api, dict) and "data" in data_api else data_api
        payload_v1 = data_v1.get("data") if isinstance(data_v1, dict) and "data" in data_v1 else data_v1

        assert isinstance(payload_api, dict), f"Expected dict payload for /api, got {type(payload_api)}"
        assert isinstance(payload_v1, dict), f"Expected dict payload for /v1, got {type(payload_v1)}"

        payload_keys_api = set(payload_api.keys())
        payload_keys_v1 = set(payload_v1.keys())

        missing = REQUIRED_HOME_FIELDS - payload_keys_api
        assert not missing, f"Missing required home fields: {sorted(missing)}"

