import pytest
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room

pytestmark = pytest.mark.django_db

# -----------------------------
# EDIT THESE if your paths differ
# -----------------------------
MY_LISTINGS_API = "/api/my-listings/"
MY_LISTINGS_V1 = "/api/v1/my-listings/"

# -----------------------------
# Figma-required list item fields (EDIT THESE)
# Put exactly what the frontend reads for "My Listings" list rows.
# -----------------------------
REQUIRED_MY_LISTINGS_ITEM_FIELDS = {
    "id",
    "title",
    "price_per_month",
    "main_photo",
    "photo_count",
    "listing_state",
    "status",
    "paid_until",
}

def make_user_with_profile(username: str):
    User = get_user_model()
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="StrongP@ssword1",
    )

    # If your project has a OneToOne profile (user.profile), create it if missing.
    try:
        user.profile  # noqa: B018
    except Exception:
        try:
            from propertylist_app.models import UserProfile
            UserProfile.objects.create(user=user)
        except Exception:
            pass

    return user


def authed(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _placeholder_value_for_field(field, user):
    """
    Creates a safe placeholder value for required NOT NULL fields.
    Uses model metadata so your tests don’t break when you add required fields.
    """
    from django.db import models

    if isinstance(field, models.ForeignKey):
        rel_model = field.remote_field.model

        if rel_model == get_user_model():
            return user

        # Common pattern: Room.property_owner points to UserProfile
        if rel_model.__name__.lower() in ("userprofile", "profile"):
            try:
                return getattr(user, "profile")
            except Exception:
                return None

        # Last resort: try creating related object (may fail if it has required fields)
        try:
            return rel_model.objects.create()
        except Exception:
            return None

    it = field.get_internal_type()

    if it in ("CharField", "SlugField", "EmailField", "URLField"):
        return "x"
    if it in ("TextField",):
        return "x"
    if it in ("IntegerField", "BigIntegerField", "SmallIntegerField", "PositiveIntegerField", "PositiveSmallIntegerField"):
        return 1
    if it in ("DecimalField",):
        return Decimal("100.00")
    if it in ("FloatField",):
        return 100.0
    if it in ("BooleanField",):
        return False
    if it in ("DateTimeField",):
        return timezone.now()
    if it in ("DateField",):
        return timezone.now().date()

    return None


def make_min_valid_room(user) -> Room:
    """
    Creates a Room row that satisfies NOT NULL constraints in the test DB.
    Also tries to set ownership to the current user/profile when possible.
    """
    data = {}

    for field in Room._meta.fields:
        # Skip PK / auto fields
        if getattr(field, "primary_key", False):
            continue
        if getattr(field, "auto_created", False):
            continue

        # If field has default, DB can fill it
        if field.has_default():
            continue

        # If null allowed, can remain None
        if getattr(field, "null", False):
            continue

        # Auto timestamps
        if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            continue

        value = _placeholder_value_for_field(field, user)
        if value is not None:
            data[field.name] = value

    # Safety for your known NOT NULL field
    if "price_per_month" not in data:
        data["price_per_month"] = Decimal("1000.00")

    # Try to make it look like a “listing” if these fields exist
    # (only set if the model contains them)
    model_field_names = {f.name for f in Room._meta.fields}

    if "title" in model_field_names and "title" not in data:
        data["title"] = "Test listing"

    if "is_deleted" in model_field_names:
        data["is_deleted"] = False

    if "is_available" in model_field_names:
        data["is_available"] = True

    if "status" in model_field_names:
        # If your status is choices, "active" might not be valid; adjust if needed.
        data.setdefault("status", "active")

    if "listing_state" in model_field_names:
        # Adjust if your listing_state choices differ.
        data.setdefault("listing_state", "active")

    return Room.objects.create(**data)


def _normalise_list_response(payload):
    """
    Supports:
      - list
      - paginated dict: {"results": [...]}
    Returns the list of items.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    return None


def test_my_listings_list_item_shape_contract_api_vs_v1_and_required_fields():
    user = make_user_with_profile("contract_my_listings_user")
    c = authed(user)

    # Ensure at least one listing exists for this user in the test DB
    make_min_valid_room(user)

    r_api = c.get(MY_LISTINGS_API)
    r_v1 = c.get(MY_LISTINGS_V1)

    assert r_api.status_code == 200, r_api.data
    assert r_v1.status_code == 200, r_v1.data

    data_api = r_api.json()
    data_v1 = r_v1.json()

    items_api = _normalise_list_response(data_api)
    items_v1 = _normalise_list_response(data_v1)

    assert isinstance(items_api, list), f"/api must return list or paginated dict, got {type(data_api)}"
    assert isinstance(items_v1, list), f"/api/v1 must return list or paginated dict, got {type(data_v1)}"

    assert items_api, "my-listings returned empty list even after creating a Room. Check endpoint filters/ownership rules."
    assert items_v1, "my-listings v1 returned empty list even after creating a Room. Check endpoint filters/ownership rules."

    first_api = items_api[0]
    first_v1 = items_v1[0]

    assert isinstance(first_api, dict), f"List item must be dict, got {type(first_api)}"
    assert isinstance(first_v1, dict), f"List item must be dict, got {type(first_v1)}"

    # Contract parity: /api and /api/v1 item keys must match
    assert set(first_api.keys()) == set(first_v1.keys()), (
        f"My Listings item keys differ.\n/api: {sorted(first_api.keys())}\n/v1: {sorted(first_v1.keys())}"
    )

    # Strict “Figma required fields” check (you must fill this set)
    if not REQUIRED_MY_LISTINGS_ITEM_FIELDS:
        pytest.fail(
            "REQUIRED_MY_LISTINGS_ITEM_FIELDS is empty.\n"
            f"Paste your Figma-required My Listings keys here. Current keys: {sorted(first_api.keys())}"
        )

    missing = REQUIRED_MY_LISTINGS_ITEM_FIELDS - set(first_api.keys())
    assert not missing, f"Missing required My Listings fields: {sorted(missing)}"