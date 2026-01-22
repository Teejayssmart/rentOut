import pytest
from django.contrib.auth.models import User
from django.test import override_settings

from propertylist_app.models import Room, RoomCategorie

pytestmark = pytest.mark.django_db


def _mk_user(username: str) -> User:
    return User.objects.create_user(username=username, password="pass12345")


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
        # keep your existing defaults if you have them; this override is scoped to this test file
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.ScopedRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            # this matches ReportCreateView.throttle_scope :contentReference[oaicite:4]{index=4}
            "report-create": "1/minute",
        },
    }
)
def test_report_create_throttles_after_limit(api_client):
    reporter = _mk_user("throttle_user")
    landlord = _mk_user("throttle_landlord")
    room = _mk_room(landlord)

    api_client.force_authenticate(user=reporter)

    payload = {"target_type": "room", "object_id": room.id, "reason": "abuse", "details": "x"}

    # first request allowed
    r1 = api_client.post("/api/v1/reports/", payload, format="json")
    assert r1.status_code in (200, 201)

    # second request within the same minute should be throttled
    r2 = api_client.post("/api/v1/reports/", payload, format="json")
    assert r2.status_code == 429
