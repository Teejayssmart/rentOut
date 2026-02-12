import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from uuid import uuid4

pytestmark = pytest.mark.django_db

User = get_user_model()


def make_user():
    uid = uuid4().hex[:12]
    return User.objects.create_user(
        username=f"user_{uid}",
        email=f"user_{uid}@example.com",
        password="Passw0rd!123",
    )


def unique_title(prefix="Test room"):
    return f"{prefix} {uuid4().hex[:8]}"


def _extract_list(res):
    """
    Supports:
    - ok_response wrapper: {"ok": True, "data": ...}
    - paginated: {"count": ..., "results": [...]}
    - plain list: [...]
    """
    payload = res.data

    # unwrap ok_response
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]

    # unwrap pagination
    if isinstance(payload, dict) and "results" in payload:
        payload = payload["results"]

    return payload


def test_min_rating_filters_rooms(api_client, room_factory):
    r1 = room_factory(
        title=unique_title(),
        avg_rating=3.5,
        property_owner=make_user(),
    )
    r2 = room_factory(
        title=unique_title(),
        avg_rating=4.2,
        property_owner=make_user(),
    )

    url = reverse("v1:search-rooms")
    res = api_client.get(url, {"min_rating": 4})

    assert res.status_code == 200
    data = _extract_list(res)
    ids = [x["id"] for x in data]

    assert r2.id in ids
    assert r1.id not in ids


def test_max_rating_filters_rooms(api_client, room_factory):
    r1 = room_factory(
        title=unique_title(),
        avg_rating=2.0,
        property_owner=make_user(),
    )
    r2 = room_factory(
        title=unique_title(),
        avg_rating=4.5,
        property_owner=make_user(),
    )

    url = reverse("v1:search-rooms")
    res = api_client.get(url, {"max_rating": 3})

    assert res.status_code == 200
    data = _extract_list(res)
    ids = [x["id"] for x in data]

    assert r1.id in ids
    assert r2.id not in ids


def test_rating_range_filters_rooms(api_client, room_factory):
    r1 = room_factory(
        title=unique_title(),
        avg_rating=3.9,
        property_owner=make_user(),
    )
    r2 = room_factory(
        title=unique_title(),
        avg_rating=4.0,
        property_owner=make_user(),
    )
    r3 = room_factory(
        title=unique_title(),
        avg_rating=4.8,
        property_owner=make_user(),
    )

    url = reverse("v1:search-rooms")
    res = api_client.get(url, {"min_rating": 4.0, "max_rating": 4.7})

    assert res.status_code == 200
    data = _extract_list(res)
    ids = [x["id"] for x in data]

    assert r2.id in ids
    assert r1.id not in ids
    assert r3.id not in ids


def test_min_rating_greater_than_max_rating_returns_400(api_client):
    url = reverse("v1:search-rooms")
    res = api_client.get(url, {"min_rating": 5, "max_rating": 4})

    assert res.status_code == 400

    err = res.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "min_rating" in err.get("field_errors", {})


def test_invalid_rating_returns_400(api_client):
    url = reverse("v1:search-rooms")
    res = api_client.get(url, {"min_rating": "abc"})
    
    assert res.status_code == 400

    err = res.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "min_rating" in err.get("field_errors", {})
