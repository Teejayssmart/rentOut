import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def assert_exact_keys(obj: dict, expected_keys: set[str]) -> None:
    assert isinstance(obj, dict), f"Expected dict, got {type(obj)}"
    assert set(obj.keys()) == expected_keys, f"Keys mismatch.\nGot: {set(obj.keys())}\nExpected: {expected_keys}"


def assert_is_bool(v, name: str) -> None:
    assert isinstance(v, bool), f"{name} must be bool, got {type(v)}"


def assert_is_int(v, name: str) -> None:
    assert isinstance(v, int), f"{name} must be int, got {type(v)}"


def test_rooms_list_contract_api_and_v1_match_shape():
    """
    Observed: /api/rooms/ returns a LIST of room dicts (no pagination envelope).
    Locks:
      - top-level type is list
      - first item is dict
      - first item has exact key set
      - /api and /api/v1 return same item key set
    """
    client = APIClient()

    # Use literal paths to avoid reverse() name mismatches
    url_api = "/api/rooms/"
    url_v1 = "/api/v1/rooms/"

    r_api = client.get(url_api)
    assert r_api.status_code == 200, r_api.data
    data_api = r_api.json()

    r_v1 = client.get(url_v1)
    assert r_v1.status_code == 200, r_v1.data
    data_v1 = r_v1.json()

    assert isinstance(data_api, list), f"/api rooms must be list, got {type(data_api)}"
    assert isinstance(data_v1, list), f"/api/v1 rooms must be list, got {type(data_v1)}"

    # If empty list, still valid contract; enforce parity.
    if not data_api or not data_v1:
        assert data_api == data_v1, "If empty, both should be empty for parity in this test."
        return

    first_api = data_api[0]
    first_v1 = data_v1[0]
    assert isinstance(first_api, dict), f"First item must be dict, got {type(first_api)}"
    assert isinstance(first_v1, dict), f"First item must be dict, got {type(first_v1)}"

    expected_item_keys = {
        "accessible_entry",
        "allow_search_indexing_effective",
        "allow_search_indexing_override",
        "availability_from_time",
        "availability_to_time",
        "available_from",
        "avg_rating",
        "bathroom_type",
        "bills_included",
        "category",
        "created_at",
        "deleted_at",
        "description",
        "distance_miles",
        "existing_flatmate_age",
        "existing_flatmate_gender",
        "existing_flatmate_language",
        "existing_flatmate_lgbtqia_household",
        "existing_flatmate_nationality",
        "existing_flatmate_occupation",
        "existing_flatmate_pets",
        "existing_flatmate_smoking",
        "free_to_contact",
        "furnished",
        "household_bedrooms_max",
        "household_bedrooms_min",
        "household_environment",
        "household_type",
        "id",
        "image",
        "inclusive_household",
        "is_available",
        "is_deleted",
        "is_saved",
        "is_shared_room",
        "latitude",
        "listing_state",
        "location",
        "longitude",
        "main_photo",
        "max_age",
        "max_occupants",
        "max_stay_months",
        "min_age",
        "min_stay_months",
        "number_of_bathrooms",
        "number_of_bedrooms",
        "number_rating",
        "owner_avatar",
        "owner_name",
        "paid_until",
        "parking_available",
        "pets_allowed",
        "photo_count",
        "preferred_flatmate_gender",
        "preferred_flatmate_language",
        "preferred_flatmate_lgbtqia",
        "preferred_flatmate_max_age",
        "preferred_flatmate_min_age",
        "preferred_flatmate_nationality",
        "preferred_flatmate_occupation",
        "preferred_flatmate_partners_allowed",
        "preferred_flatmate_pets",
        "preferred_flatmate_smoking",
        "preferred_flatmate_vegan_vegetarian",
        "price_per_month",
        "property_owner",
        "property_type",
        "room_for",
        "room_size",
        "security_deposit",
        "shared_living_space",
        "smoking_allowed_in_property",
        "status",
        "suitable_for",
        "title",
        "updated_at",
        "view_available_custom_dates",
        "view_available_days_mode",
    }

    assert_exact_keys(first_api, expected_item_keys)
    assert_exact_keys(first_v1, expected_item_keys)

    # Minimal type locks for key fields
    assert_is_int(first_api["id"], "id")
    assert_is_bool(first_api["is_saved"], "is_saved")
    assert_is_bool(first_api["is_available"], "is_available")
    assert_is_bool(first_api["is_deleted"], "is_deleted")
    assert_is_bool(first_api["is_shared_room"], "is_shared_room")

    # Parity
    assert set(first_api.keys()) == set(first_v1.keys()) == expected_item_keys