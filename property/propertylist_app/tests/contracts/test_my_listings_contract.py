import pytest
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room

pytestmark = pytest.mark.django_db


# -----------------------------
# CANONICAL V1 ENDPOINT ONLY
# -----------------------------
MY_LISTINGS_V1 = "/api/v1/my-listings/"


# -----------------------------
# Figma-required list item fields (keep/edit as needed)
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
            UserProfile.objects.get_or_create(user=user)
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

        if rel_model.__name__.lower() in ("userprofile", "profile"):
            try:
                return getattr(user, "profile")
            except Exception:
                return None

        try:
            return rel_model.objects.create()
        except Exception:
            return None

    it = field.get_internal_type()

    if it in ("CharField", "SlugField", "EmailField", "URLField"):
        return "x"
    if it in ("TextField",):
        return "x"
    if it in (
        "IntegerField",
        "BigIntegerField",
        "SmallIntegerField",
        "PositiveIntegerField",
        "PositiveSmallIntegerField",
    ):
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
        if getattr(field, "primary_key", False) or getattr(field, "auto_created", False):
            continue

        if field.has_default():
            continue

        if getattr(field, "null", False):
            continue

        if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            continue

        value = _placeholder_value_for_field(field, user)
        if value is not None:
            data[field.name] = value

    # Safety for your known NOT NULL field
    data.setdefault("price_per_month", Decimal("1000.00"))

    model_field_names = {f.name for f in Room._meta.fields}

    if "title" in model_field_names:
        data.setdefault("title", "Test listing")

    if "property_owner" in model_field_names:
        data["property_owner"] = user

    if "is_deleted" in model_field_names:
        data["is_deleted"] = False

    if "is_available" in model_field_names:
        data["is_available"] = True

    if "status" in model_field_names:
        data.setdefault("status", "active")

    if "listing_state" in model_field_names:
        data.setdefault("listing_state", "active")

    return Room.objects.create(**data)


def _normalise_list_response(payload):
    """
    Supports:
      - list
      - paginated dict: {"results": [...]}
      - ok envelope: {"ok": True, "data": <list|dict>}
    Returns the list of items or None.
    """
    if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
        payload = payload["data"]

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]

    return None


def test_my_listings_list_item_shape_contract_v1_and_required_fields():
    user = make_user_with_profile("contract_my_listings_user")
    c = authed(user)

    # Ensure at least one listing exists for this user in the test DB
    make_min_valid_room(user)

    r = c.get(MY_LISTINGS_V1)
    assert r.status_code == 200, getattr(r, "content", b"")

    data = r.json()
    items = _normalise_list_response(data)

    assert isinstance(items, list), (
        f"/api/v1/my-listings/ must return list or paginated dict, got {type(data)}"
    )

    assert items, (
        "my-listings returned empty list even after creating a Room. "
        "Check endpoint filters/ownership rules."
    )

    first = items[0]
    assert isinstance(first, dict), f"List item must be dict, got {type(first)}"

    missing = REQUIRED_MY_LISTINGS_ITEM_FIELDS - set(first.keys())
    assert not missing, f"Missing required My Listings fields: {sorted(missing)}"
