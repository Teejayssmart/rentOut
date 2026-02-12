import pytest
from django.contrib.auth.models import User
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


def test_user_cannot_report_own_room(api_client):
    owner = _mk_user("owner_report_self")
    room = _mk_room(owner)

    api_client.force_authenticate(user=owner)
    r = api_client.post(
        "/api/v1/reports/",
        {"target_type": "room", "object_id": room.id, "reason": "abuse", "details": "x"},
        format="json",
    )
    assert r.status_code == 400
    # reason: A4 envelope stores field-level validation errors under field_errors
    assert r.data.get("ok") is False
    assert r.data.get("code") == "validation_error"
    assert "object_id" in r.data.get("field_errors", {})




