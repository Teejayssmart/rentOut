import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room

pytestmark = pytest.mark.django_db

# -----------------------------
# CANONICAL V1 ONLY
# -----------------------------
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

            UserProfile.objects.get_or_create(user=user)
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
    Creates a Room that satisfies NOT NULL fields in tests.
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
    """
    Try list first using v1; if empty / blocked, fall back to creating a room.
    """
    r = c.get("/api/v1/rooms/")
    if r.status_code == 200:
        data = r.json()

        # your rooms list might be:
        # - list
        # - paginated dict {"results": [...]}
        if isinstance(data, dict) and data.get("ok") is True and "data" in data:
            data = data["data"]

        if isinstance(data, dict) and isinstance(data.get("results"), list):
            data = data["results"]

        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and "id" in first:
                return int(first["id"])

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


def _unwrap_ok_envelope(payload):
    """
    If response uses your success envelope: {"ok": True, "data": ...}
    unwrap to the inner data so the rest of the contract stays stable.
    """
    if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
        return payload["data"]
    return payload


# -----------------------------
# Test (V1 ONLY)
# -----------------------------
def test_room_preview_step5_strict_fields_and_media_url_rules_v1():
    user = make_user_with_profile("contract_step5_user")
    c = make_authed_client(user)

    room_id = get_room_id_for_preview(c, user)

    r = c.get(PREVIEW_V1.format(room_id=room_id))
    assert r.status_code == 200, getattr(r, "content", b"")

    payload = _unwrap_ok_envelope(r.json())

    assert isinstance(payload, dict), f"Preview payload must be dict, got {type(payload)}"

    # 1) top-level contract for Step 5 payload
    assert set(payload.keys()) == REQUIRED_TOP_LEVEL_KEYS, (
        "Top-level keys are not what Step 5 contract expects.\n"
        f"Expected: {sorted(REQUIRED_TOP_LEVEL_KEYS)}\n"
        f"Got: {sorted(payload.keys())}"
    )

    # 2) room object must exist and be a dict
    room = payload.get("room")
    assert isinstance(room, dict), f"payload['room'] must be dict, got {type(room)}"

    # 3) strict Step 5 fields inside room
    if not REQUIRED_ROOM_FIELDS:
        pytest.fail(
            "REQUIRED_ROOM_FIELDS is empty.\n"
            f"Paste your Step 5 required room keys here. Current room keys: {sorted(room.keys())}"
        )

    missing = REQUIRED_ROOM_FIELDS - set(room.keys())
    assert not missing, (
        f"Missing required Step 5 room fields: {sorted(missing)}\n"
        f"Room keys present: {sorted(room.keys())}"
    )

    # 4) URL rules across entire payload (room + photos)
    urls = _walk_urls(payload)
    if EXPECT_ABSOLUTE_MEDIA_URLS:
        bad = [(k, v) for (k, v) in urls if v and not _is_absolute(v)]
        assert not bad, f"Expected absolute URLs but found relative/invalid: {bad[:10]}"
    else:
        bad = [(k, v) for (k, v) in urls if v and _is_absolute(v)]
        assert not bad, f"Expected relative URLs but found absolute: {bad[:10]}"
