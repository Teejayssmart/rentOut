import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room

pytestmark = pytest.mark.django_db

PREVIEW_API = "/api/rooms/{room_id}/preview/"
PREVIEW_V1 = "/api/v1/rooms/{room_id}/preview/"


# -----------------------------
# Step 5 contract (Figma)
# -----------------------------
# Top-level keys your endpoint returns (you printed: ['photos', 'room'])
REQUIRED_TOP_LEVEL_KEYS = {"room", "photos"}

# These are the REQUIRED fields INSIDE payload["room"] for Step 5 UI stability.
# Update this list to match what your frontend reads.
REQUIRED_ROOM_FIELDS: set[str] = {
    "id",
    "title",
    "price_per_month",
    "location",
    # add more when needed, e.g.:
    # "city",
    # "postcode",
    # "room_type",
    # "deposit",
}

# URL rules: choose one behaviour and lock it.
EXPECT_ABSOLUTE_MEDIA_URLS = True  # set False if frontend expects relative


# -----------------------------
# Auth + profile helper
# -----------------------------
def make_user_with_profile(username: str = "contract_step5_user"):
    User = get_user_model()
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="StrongP@ssword1",
    )

    # Ensure user.profile exists if your project expects it
    try:
        user.profile  # noqa: B018
    except Exception:
        try:
            from propertylist_app.models import UserProfile

            UserProfile.objects.create(user=user)
        except Exception:
            pass

    return user


def make_authed_client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


# -----------------------------
# Room creation helper (avoid NOT NULL failures)
# -----------------------------
def _placeholder_value_for_field(field, user):
    from django.db import models

    if isinstance(field, models.ForeignKey):
        rel_model = field.remote_field.model
        if rel_model == get_user_model():
            return user

        # common: Room.owner/landlord -> profile model
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
        # fallback money value
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
    Creates a Room that satisfies NOT NULL fields in SQLite tests.
    Uses model metadata so it won’t break when you add another required field.
    """
    data = {}

    for field in Room._meta.fields:
        if getattr(field, "primary_key", False):
            continue
        if getattr(field, "auto_created", False):
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

    # Hard safety for the field you already hit
    if "price_per_month" not in data:
        data["price_per_month"] = Decimal("1000.00")

    return Room.objects.create(**data)


def get_room_id_for_preview(c: APIClient, user) -> int:
    # Try list first (if any exist and list endpoint is allowed)
    r = c.get("/api/rooms/")
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and "id" in first:
                return int(first["id"])

    # Fallback: create a valid room for preview
    room = make_min_valid_room(user)
    return int(room.id)


# -----------------------------
# URL checks
# -----------------------------
def _is_absolute(url: str) -> bool:
    return isinstance(url, str) and (url.startswith("http://") or url.startswith("https://"))


def _walk_urls(obj, found=None):
    """
    Collect any fields likely to be URLs:
      - keys containing 'url'
      - keys ending with '_link'
    """
    if found is None:
        found = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if isinstance(v, str) and ("url" in lk or lk.endswith("_link")):
                found.append((k, v))
            else:
                _walk_urls(v, found)
    elif isinstance(obj, list):
        for it in obj:
            _walk_urls(it, found)

    return found


# -----------------------------
# Test
# -----------------------------
def test_room_preview_step5_strict_fields_and_media_url_rules_api_vs_v1():
    user = make_user_with_profile("contract_step5_user")
    c = make_authed_client(user)

    room_id = get_room_id_for_preview(c, user)

    r_api = c.get(PREVIEW_API.format(room_id=room_id))
    r_v1 = c.get(PREVIEW_V1.format(room_id=room_id))

    assert r_api.status_code == 200, r_api.data
    assert r_v1.status_code == 200, r_v1.data

    data_api = r_api.json()
    data_v1 = r_v1.json()

    assert isinstance(data_api, dict)
    assert isinstance(data_v1, dict)

    # 1) /api and /api/v1 parity (top-level keys)
    assert set(data_api.keys()) == set(data_v1.keys()), (
        f"Preview keys differ.\n/api: {sorted(data_api.keys())}\n/v1: {sorted(data_v1.keys())}"
    )

    # 2) top-level contract for Step 5 payload
    assert set(data_api.keys()) == REQUIRED_TOP_LEVEL_KEYS, (
        "Top-level keys are not what Step 5 contract expects.\n"
        f"Expected: {sorted(REQUIRED_TOP_LEVEL_KEYS)}\n"
        f"Got: {sorted(data_api.keys())}"
    )

    # 3) room object must exist and be a dict
    room_api = data_api.get("room")
    room_v1 = data_v1.get("room")

    assert isinstance(room_api, dict), f"payload['room'] must be dict, got {type(room_api)}"
    assert isinstance(room_v1, dict), f"payload['room'] must be dict, got {type(room_v1)}"

    # parity inside room keys
    assert set(room_api.keys()) == set(room_v1.keys()), (
        f"Room keys differ.\n/api: {sorted(room_api.keys())}\n/v1: {sorted(room_v1.keys())}"
    )

    # 4) strict Step 5 fields inside room
    if not REQUIRED_ROOM_FIELDS:
        pytest.fail(
            "REQUIRED_ROOM_FIELDS is empty.\n"
            f"Paste your Step 5 required room keys here. Current room keys: {sorted(room_api.keys())}"
        )

    missing = REQUIRED_ROOM_FIELDS - set(room_api.keys())
    assert not missing, (
        f"Missing required Step 5 room fields: {sorted(missing)}\n"
        f"Room keys present: {sorted(room_api.keys())}"
    )

    # 5) URL rules across entire payload (room + photos)
    urls = _walk_urls(data_api)
    if EXPECT_ABSOLUTE_MEDIA_URLS:
        bad = [(k, v) for (k, v) in urls if v and not _is_absolute(v)]
        assert not bad, f"Expected absolute URLs but found relative/invalid: {bad[:10]}"
    else:
        bad = [(k, v) for (k, v) in urls if v and _is_absolute(v)]
        assert not bad, f"Expected relative URLs but found absolute: {bad[:10]}"