import pytest
from rest_framework.test import APIClient
from django.contrib.auth.models import User

from propertylist_app.models import Room, RoomCategorie

pytestmark = pytest.mark.django_db


def assert_exact_keys(obj: dict, expected_keys: set[str]) -> None:
    assert isinstance(obj, dict), f"Expected dict, got {type(obj)}"
    assert set(obj.keys()) == expected_keys, f"Keys mismatch.\nGot: {set(obj.keys())}\nExpected: {expected_keys}"


def assert_is_bool(v, name: str) -> None:
    assert isinstance(v, bool), f"{name} must be bool, got {type(v)}"


def assert_is_int(v, name: str) -> None:
    assert isinstance(v, int), f"{name} must be int, got {type(v)}"


def seed_room_if_empty():
    """
    Creates the minimum viable Room so /api/rooms/ is non-empty in a fresh test DB.
    Mirrors existing project tests that create Room with: title, category, price_per_month, property_owner.
    """
    if Room.objects.exists():
        return

    owner = User.objects.create_user(
        username="contract_room_owner",
        email="contract_room_owner@test.com",
        password="StrongP@ssword1",
    )
    cat = RoomCategorie.objects.create(name="Contract Category", active=True)

    Room.objects.create(
        title="Contract Room",
        category=cat,
        price_per_month=900,
        property_owner=owner,
    )


def get_first_room_id(client: APIClient) -> int:
    seed_room_if_empty()

    r = client.get("/api/rooms/")
    assert r.status_code == 200, r.data
    data = r.json()

    assert isinstance(data, list) and data, "Rooms list is empty even after seeding."
    assert isinstance(data[0], dict) and "id" in data[0], "Rooms list first item missing 'id'."
    return int(data[0]["id"])


def test_room_detail_contract_api_and_v1_match_shape():
    client = APIClient()
    room_id = get_first_room_id(client)

    r_api = client.get(f"/api/rooms/{room_id}/")
    r_v1 = client.get(f"/api/v1/rooms/{room_id}/")

    assert r_api.status_code == 200, r_api.data
    assert r_v1.status_code == 200, r_v1.data

    data_api = r_api.json()
    data_v1 = r_v1.json()

    assert isinstance(data_api, dict)
    assert isinstance(data_v1, dict)

    expected_keys = {
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

    assert_exact_keys(data_api, expected_keys)
    assert_exact_keys(data_v1, expected_keys)

    assert_is_int(data_api["id"], "id")
    assert_is_bool(data_api["is_saved"], "is_saved")
    assert_is_bool(data_api["is_available"], "is_available")
    assert_is_bool(data_api["is_deleted"], "is_deleted")
    assert_is_bool(data_api["is_shared_room"], "is_shared_room")

    assert set(data_api.keys()) == set(data_v1.keys()) == expected_keys