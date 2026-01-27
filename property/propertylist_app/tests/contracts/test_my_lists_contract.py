import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

# Candidate endpoints (adjust if yours differs)
MY_LISTINGS_API_CANDIDATES = [
    "/api/my-listings/",
    "/api/rooms/me/",
    "/api/rooms/my/",
    "/api/users/me/listings/",
]
MY_BOOKINGS_API = "/api/bookings/"
MY_LISTINGS_V1_CANDIDATES = [p.replace("/api/", "/api/v1/") for p in MY_LISTINGS_API_CANDIDATES]
MY_BOOKINGS_V1 = "/api/v1/bookings/"

# -----------------------------
# Update these from Figma
# -----------------------------
REQUIRED_MY_LISTINGS_ITEM_FIELDS: set[str] = set([
    # example:
    # "id", "title", "price_per_month", "photo_url", "city"
])

REQUIRED_MY_BOOKINGS_ITEM_FIELDS: set[str] = set([
    # example:
    # "id", "room", "start_date", "status"
])


def make_authed_client() -> APIClient:
    User = get_user_model()
    user = User.objects.create_user(
        username="contract_my_lists_user",
        email="contract_my_lists_user@test.com",
        password="StrongP@ssword1",
    )
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _extract_first_item(payload):
    """
    Supports:
      - list
      - paginated dict with 'results'
    """
    if isinstance(payload, list):
        return payload[0] if payload else None
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"][0] if payload["results"] else None
    return None


def _find_first_listings_endpoint(c: APIClient):
    for api_path, v1_path in zip(MY_LISTINGS_API_CANDIDATES, MY_LISTINGS_V1_CANDIDATES):
        r_api = c.get(api_path)
        r_v1 = c.get(v1_path)
        if r_api.status_code == 404 and r_v1.status_code == 404:
            continue
        return api_path, v1_path, r_api, r_v1
    return None, None, None, None


def test_my_listings_list_item_contract_api_and_v1():
    c = make_authed_client()
    api_path, v1_path, r_api, r_v1 = _find_first_listings_endpoint(c)

    if not api_path:
        pytest.skip("No My Listings endpoint found in candidates. Add your real path(s).")

    assert r_api.status_code == r_v1.status_code
    assert r_api.status_code in (200, 401, 403), r_api.data
    if r_api.status_code != 200:
        return

    data_api = r_api.json()
    data_v1 = r_v1.json()

    first_api = _extract_first_item(data_api)
    first_v1 = _extract_first_item(data_v1)

    # If no items exist, we still keep parity; skip strict item check.
    if not first_api and not first_v1:
        return

    assert isinstance(first_api, dict) and isinstance(first_v1, dict)
    assert set(first_api.keys()) == set(first_v1.keys()), (
        f"Listings item keys differ.\n/api: {sorted(first_api.keys())}\n/v1: {sorted(first_v1.keys())}"
    )

    if not REQUIRED_MY_LISTINGS_ITEM_FIELDS:
        pytest.fail(
            "REQUIRED_MY_LISTINGS_ITEM_FIELDS is empty.\n"
            f"Paste your Figma required listing-item keys here. Current keys: {sorted(first_api.keys())}"
        )

    missing = REQUIRED_MY_LISTINGS_ITEM_FIELDS - set(first_api.keys())
    assert not missing, f"Missing required My Listings item fields: {sorted(missing)}"


def test_my_bookings_list_item_contract_api_and_v1():
    c = make_authed_client()

    r_api = c.get(MY_BOOKINGS_API)
    r_v1 = c.get(MY_BOOKINGS_V1)

    assert r_api.status_code == r_v1.status_code
    assert r_api.status_code in (200, 401, 403), r_api.data
    if r_api.status_code != 200:
        return

    data_api = r_api.json()
    data_v1 = r_v1.json()

    first_api = _extract_first_item(data_api)
    first_v1 = _extract_first_item(data_v1)

    if not first_api and not first_v1:
        return

    assert isinstance(first_api, dict) and isinstance(first_v1, dict)
    assert set(first_api.keys()) == set(first_v1.keys()), (
        f"Bookings item keys differ.\n/api: {sorted(first_api.keys())}\n/v1: {sorted(first_v1.keys())}"
    )

    if not REQUIRED_MY_BOOKINGS_ITEM_FIELDS:
        pytest.fail(
            "REQUIRED_MY_BOOKINGS_ITEM_FIELDS is empty.\n"
            f"Paste your Figma required booking-item keys here. Current keys: {sorted(first_api.keys())}"
        )

    missing = REQUIRED_MY_BOOKINGS_ITEM_FIELDS - set(first_api.keys())
    assert not missing, f"Missing required My Bookings item fields: {sorted(missing)}"