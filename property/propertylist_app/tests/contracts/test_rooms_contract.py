import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from propertylist_app.models import Room, RoomCategorie

pytestmark = pytest.mark.django_db


# -----------------------------
# CANONICAL V1 ENDPOINT ONLY
# -----------------------------
ROOMS_LIST_V1 = "/api/v1/rooms/"


def assert_exact_keys(obj: dict, expected_keys: set[str]) -> None:
    assert isinstance(obj, dict), f"Expected dict, got {type(obj)}"
    assert set(obj.keys()) == expected_keys, (
        f"Keys mismatch.\nGot: {set(obj.keys())}\nExpected: {expected_keys}"
    )


def assert_is_bool(v, name: str) -> None:
    assert isinstance(v, bool), f"{name} must be bool, got {type(v)}"


def assert_is_int(v, name: str) -> None:
    assert isinstance(v, int), f"{name} must be int, got {type(v)}"


def seed_room_if_empty() -> None:
    """
    Reason: contract tests must not skip or fail due to empty fresh test DB.
    Creates the minimum viable Room so /api/v1/rooms/ returns at least one item.
    """
    if Room.objects.exists():
        return

    User = get_user_model()
    owner = User.objects.create_user(
        username="contract_rooms_owner",
        email="contract_rooms_owner@test.com",
        password="StrongP@ssword1",
    )
    cat = RoomCategorie.objects.create(name="Contract Rooms Category", active=True)

    Room.objects.create(
        title="Contract Room",
        category=cat,
        price_per_month=900,
        property_owner=owner,
    )


def test_rooms_list_contract_v1_strict_item_shape():
    """
    Locks (v1 only):
      - status 200
      - top-level type is list
      - first item is dict
      - first item has exact key set
      - minimal type checks for key fields
    """
    seed_room_if_empty()

    client = APIClient()
    r = client.get(ROOMS_LIST_V1)

    # NOTE: avoid r.data here; if the view ever returns a non-DRF response,
    # r.data can raise. json()/content are always safe.
    assert r.status_code == 200, getattr(r, "content", b"")
    data = r.json()

    assert isinstance(data, list), f"/api/v1/rooms/ must return list, got {type(data)}"
    assert data, "Rooms list is empty even after seeding."

    first = data[0]
    assert isinstance(first, dict), f"First item must be dict, got {type(first)}"

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

    assert_exact_keys(first, expected_item_keys)

    # Minimal type locks for key fields
    assert_is_int(first["id"], "id")
    assert_is_bool(first["is_saved"], "is_saved")
    assert_is_bool(first["is_available"], "is_available")
    assert_is_bool(first["is_deleted"], "is_deleted")
    assert_is_bool(first["is_shared_room"], "is_shared_room")
