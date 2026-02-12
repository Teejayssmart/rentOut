import pytest
from django.contrib.auth.models import User
from django.core.cache import caches
from django.test import override_settings
from rest_framework.settings import api_settings

from propertylist_app.models import Room, RoomCategorie

pytestmark = pytest.mark.django_db


def _mk_user(username: str) -> User:
    return User.objects.create_user(
        username=username,
        password="pass12345",
        email=f"{username}@test.com",
    )


def _mk_room(owner: User, status: str = "active") -> Room:
    cat = RoomCategorie.objects.create(name="General", key=f"general-{owner.username}")
    return Room.objects.create(
        title=f"Room {owner.username}",
        description="desc",
        price_per_month="500.00",
        location="London",
        category=cat,
        property_owner=owner,
        property_type="flat",
        status=status,
    )


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.ScopedRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "report-create": "1/min",
        },
    }
)
def test_report_create_throttles_after_limit(api_client):
    # Why this exists:
    # - cache counters from other tests can make throttling unpredictable
    # - DRF caches REST_FRAMEWORK in api_settings; reload forces it to use override_settings
    caches["default"].clear()
    api_settings.reload()

    reporter = _mk_user("throttle_user")
    landlord = _mk_user("throttle_landlord")
    room = _mk_room(landlord)

    api_client.force_authenticate(user=reporter)

    payload = {
        "target_type": "room",
        "object_id": room.id,
        "reason": "abuse",
        "details": "x",
    }

    # 1st request should pass
    r1 = api_client.post("/api/v1/reports/", payload, format="json")
    assert r1.status_code in (200, 201), getattr(r1, "data", r1.content)

    # DEBUG: confirm what DRF stored after the first request
    key = f"throttle_report-create_{reporter.id}"
    print("\n--- AFTER r1 ---")
    print("key:", key)
    print("api_settings.DEFAULT_THROTTLE_RATES:", api_settings.DEFAULT_THROTTLE_RATES)
    print("default cache value:", caches["default"].get(key))

    # 2nd request should be throttled
    r2 = api_client.post("/api/v1/reports/", payload, format="json")
    print("\n--- AFTER r2 ---")
    print("default cache value:", caches["default"].get(key))
    assert r2.status_code == 429, getattr(r2, "data", r2.content)

