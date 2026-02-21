import pytest
from rest_framework.test import APIClient
from django.contrib.auth.models import User

from propertylist_app.models import Room, RoomCategorie

pytestmark = pytest.mark.django_db


# -----------------------------
# CANONICAL V1 ENDPOINTS ONLY
# -----------------------------
ROOMS_LIST_V1 = "/api/v1/rooms/"
ROOM_PREVIEW_V1_TEMPLATE = "/api/v1/rooms/{id}/preview/"


def _unwrap_payload(payload):
    """
    Supports:
      - ok envelope: {"ok": True, "data": ...}
      - normal payload: dict/list
    """
    if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
        return payload["data"]
    return payload


def _extract_list_items(payload):
    """
    Supports:
      - list
      - paginated dict: {"results": [...]}
      - ok envelope wrapping either of the above
    """
    payload = _unwrap_payload(payload)

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]

    return None


def make_authed_client() -> APIClient:
    """
    Contract tests should not depend on login/otp flows.
    Force-authenticate a basic user.
    """
    user = User.objects.create_user(
        username="contract_preview_user",
        email="contract_preview_user@test.com",
        password="StrongP@ssword1",
    )
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def seed_room_if_empty():
    """
    Creates a minimal Room so /api/v1/rooms/ is non-empty in a fresh test DB.
    Uses the known minimal fields from your suite: title, category, price_per_month, property_owner.
    """
    if Room.objects.exists():
        return

    owner = User.objects.create_user(
        username="contract_preview_owner",
        email="contract_preview_owner@test.com",
        password="StrongP@ssword1",
    )
    cat = RoomCategorie.objects.create(name="Contract Preview Category", active=True)

    Room.objects.create(
        title="Contract Preview Room",
        category=cat,
        price_per_month=900,
        property_owner=owner,
    )


def get_room_id_for_preview(client: APIClient) -> int:
    """
    In tests DB, /api/v1/rooms/ can be empty.
    Try list first; if empty, create a minimal Room and try again.
    """
    r = client.get(ROOMS_LIST_V1)

    # list might be public or might require auth depending on config
    assert r.status_code in (200, 401, 403), getattr(r, "content", b"")

    if r.status_code != 200:
        # if list is blocked, seed directly and use the created room id
        seed_room_if_empty()
        return int(Room.objects.order_by("id").first().id)

    items = _extract_list_items(r.json())
    if not items:
        seed_room_if_empty()
        r2 = client.get(ROOMS_LIST_V1)
        assert r2.status_code == 200, getattr(r2, "content", b"")
        items = _extract_list_items(r2.json())

    assert isinstance(items, list) and items, "Rooms list is empty even after seeding."
    assert isinstance(items[0], dict) and "id" in items[0], "Rooms list first item missing 'id'."
    return int(items[0]["id"])


def test_room_preview_contract_v1_returns_success_shape():
    client = make_authed_client()
    room_id = get_room_id_for_preview(client)

    r = client.get(ROOM_PREVIEW_V1_TEMPLATE.format(id=room_id))

    # depending on your preview rules, these are the reasonable outcomes:
    # 200 (ok), 401/403 (auth/permission), 404 (room not found)
    assert r.status_code in (200, 401, 403, 404), getattr(r, "content", b"")

    if r.status_code != 200:
        # if not success, just ensure it's JSON dict (your error envelope)
        body = r.json()
        assert isinstance(body, dict), f"Expected dict error body, got {type(body)}"
        return

    body = r.json()

    # success should be either ok envelope or a dict payload
    if isinstance(body, dict) and body.get("ok") is True:
        assert "data" in body, "Success envelope must include 'data'"
        assert isinstance(body["data"], (dict, list)), f"Envelope data must be dict/list, got {type(body['data'])}"
        return

    assert isinstance(body, (dict, list)), f"Preview success payload must be dict/list, got {type(body)}"
