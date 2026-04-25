import pytest
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, Booking

pytestmark = pytest.mark.django_db


# -----------------------------
# CANONICAL V1 ENDPOINTS ONLY
# -----------------------------
MY_LISTINGS_V1 = "/api/v1/my-listings/"
MY_BOOKINGS_V1 = "/api/v1/bookings/"


def make_authed_client() -> tuple[APIClient, object]:
    """
    Contract tests should not depend on login/otp flows.
    Force-authenticate a user at the DRF test-client level.
    """
    User = get_user_model()
    user = User.objects.create_user(
        username="contract_my_lists_user",
        email="contract_my_lists_user@test.com",
        password="StrongP@ssword1",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def _ensure_profile(user):
    """
    Some projects require user.profile to exist.
    Create it safely if the model exists.
    """
    try:
        _ = user.profile
        return
    except Exception:
        pass

    try:
        from propertylist_app.models import UserProfile
        UserProfile.objects.get_or_create(user=user)
    except Exception:
        return


def _normalise_list_payload(payload):
    """
    Supports:
      - list
      - paginated dict: {"results": [...]}
      - ok envelope: {"ok": True, "data": <list|dict>}
    Returns list or None.
    """
    if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
        payload = payload["data"]

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]

    return None


def _create_min_room_for_owner(owner) -> Room:
    """
    Create a minimal Room that satisfies NOT NULL constraints.
    This mirrors the approach used in your other v1-only listing contract test.
    """
    _ensure_profile(owner)

    data = {}

    for field in Room._meta.fields:
        if field.primary_key or field.auto_created:
            continue

        if field.has_default():
            continue

        if field.null:
            continue

        if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            continue

        # Try sensible defaults by field type
        it = field.get_internal_type()

        if it in ("CharField", "SlugField", "EmailField", "URLField", "TextField"):
            data.setdefault(field.name, "x")
        elif it in (
            "IntegerField",
            "BigIntegerField",
            "SmallIntegerField",
            "PositiveIntegerField",
            "PositiveSmallIntegerField",
        ):
            data.setdefault(field.name, 1)
        elif it == "DecimalField":
            data.setdefault(field.name, Decimal("1000.00"))
        elif it == "FloatField":
            data.setdefault(field.name, 100.0)
        elif it == "BooleanField":
            data.setdefault(field.name, False)
        elif it == "DateTimeField":
            data.setdefault(field.name, timezone.now())
        elif it == "DateField":
            data.setdefault(field.name, timezone.now().date())
        else:
            # ForeignKey handling
            from django.db import models

            if isinstance(field, models.ForeignKey):
                rel_model = field.remote_field.model

                if rel_model == get_user_model():
                    data.setdefault(field.name, owner)
                elif rel_model.__name__.lower() in ("userprofile", "profile"):
                    try:
                        data.setdefault(field.name, owner.profile)
                    except Exception:
                        pass
                else:
                    # Last resort: try to create related object
                    try:
                        data.setdefault(field.name, rel_model.objects.create())
                    except Exception:
                        pass

    # Common fields you almost certainly have
    model_field_names = {f.name for f in Room._meta.fields}

    if "title" in model_field_names:
        data["title"] = "Contract Listing"

    if "price_per_month" in model_field_names:
        data["price_per_month"] = Decimal("1000.00")

    if "property_owner" in model_field_names:
        data["property_owner"] = owner

    if "is_deleted" in model_field_names:
        data["is_deleted"] = False

    if "is_available" in model_field_names:
        data["is_available"] = True

    if "status" in model_field_names:
        data.setdefault("status", "active")

    if "listing_state" in model_field_names:
        data.setdefault("listing_state", "active")

    return Room.objects.create(**data)


def _create_min_booking(user, room) -> Booking:
    """
    Create a minimal Booking that satisfies NOT NULL constraints.
    Your earlier failure showed Booking.start/end are required.
    """
    start = timezone.now() + timezone.timedelta(days=2)
    end = start + timezone.timedelta(hours=1)

    data = {
        "user": user,
        "room": room,
        "start": start,
        "end": end,
    }

    # If status exists and is NOT NULL, set a sensible default
    booking_field_names = {f.name for f in Booking._meta.fields}
    if "status" in booking_field_names:
        data.setdefault("status", "active")

    return Booking.objects.create(**data)


def test_my_listings_list_item_contract_v1():
    c, user = make_authed_client()

    # Create at least one listing for this user so the endpoint returns non-empty list
    _create_min_room_for_owner(user)

    r = c.get(MY_LISTINGS_V1)
    assert r.status_code == 200, getattr(r, "content", b"")

    payload = r.json()
    items = _normalise_list_payload(payload)

    assert isinstance(items, list), f"Expected list or paginated dict, got {type(payload)}"
    assert items, "My Listings returned empty list even after creating a Room."

    first = items[0]
    assert isinstance(first, dict), f"Expected list item dict, got {type(first)}"

    required_keys = {"id", "title"}
    missing = required_keys - set(first.keys())
    assert not missing, f"Missing required My Listings keys: {sorted(missing)}"


def test_my_bookings_list_item_contract_v1():
    c, user = make_authed_client()

    # Create a listing and a booking for this user so the endpoint returns non-empty list
    room = _create_min_room_for_owner(user)
    _create_min_booking(user, room)

    r = c.get(MY_BOOKINGS_V1)
    assert r.status_code == 200, getattr(r, "content", b"")

    payload = r.json()
    items = _normalise_list_payload(payload)

    assert isinstance(items, list), f"Expected list or paginated dict, got {type(payload)}"
    assert items, "My Bookings returned empty list even after creating a Booking."

    first = items[0]
    assert isinstance(first, dict), f"Expected list item dict, got {type(first)}"

    required_keys = {"id"}
    missing = required_keys - set(first.keys())
    assert not missing, f"Missing required My Bookings keys: {sorted(missing)}"
