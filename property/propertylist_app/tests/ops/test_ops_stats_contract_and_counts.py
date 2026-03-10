import pytest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Payment, Room, RoomCategorie

User = get_user_model()


def _unwrap_ops_stats_response(response):
    assert response.status_code == 200, response.data
    body = response.json()
    assert set(body.keys()) == {"ok", "message", "data"}
    assert body["ok"] is True
    assert isinstance(body["data"], dict)
    return body["data"]


@pytest.mark.django_db
def test_ops_stats_schema_contract_exact_keys_and_types():
    admin = User.objects.create_user(
        username="admin_contract",
        password="pass123",
        email="admin_contract@example.com",
        is_staff=True,
    )
    c = APIClient()
    c.force_authenticate(user=admin)

    url = reverse("v1:ops-stats")
    r = c.get(url)
    data = _unwrap_ops_stats_response(r)

    # top-level keys
    assert set(data.keys()) == {
        "listings",
        "users",
        "bookings",
        "payments",
        "messages",
        "reports",
        "categories",
    }

    # listings
    assert set(data["listings"].keys()) == {"total", "active", "hidden", "deleted"}
    assert isinstance(data["listings"]["total"], int)
    assert isinstance(data["listings"]["active"], int)
    assert isinstance(data["listings"]["hidden"], int)
    assert isinstance(data["listings"]["deleted"], int)

    # users
    assert set(data["users"].keys()) == {"total"}
    assert isinstance(data["users"]["total"], int)

    # bookings
    assert set(data["bookings"].keys()) == {"last_7_days", "last_30_days", "upcoming_viewings"}
    assert isinstance(data["bookings"]["last_7_days"], int)
    assert isinstance(data["bookings"]["last_30_days"], int)
    assert isinstance(data["bookings"]["upcoming_viewings"], int)

    # payments
    assert set(data["payments"].keys()) == {"last_30_days"}
    assert isinstance(data["payments"]["last_30_days"], dict)
    assert set(data["payments"]["last_30_days"].keys()) == {"count", "sum_gbp"}
    assert isinstance(data["payments"]["last_30_days"]["count"], int)
    assert isinstance(data["payments"]["last_30_days"]["sum_gbp"], (int, float, str))

    # messages
    assert set(data["messages"].keys()) == {"threads_total", "last_7_days"}
    assert isinstance(data["messages"]["threads_total"], int)
    assert isinstance(data["messages"]["last_7_days"], int)

    # reports
    assert set(data["reports"].keys()) == {"open", "in_review"}
    assert isinstance(data["reports"]["open"], int)
    assert isinstance(data["reports"]["in_review"], int)

    # categories
    assert set(data["categories"].keys()) == {"top_active"}
    assert isinstance(data["categories"]["top_active"], list)


@pytest.mark.django_db
def test_ops_stats_requires_staff():
    non_staff = User.objects.create_user(
        username="plain_user",
        password="pass123",
        email="plain_user@example.com",
        is_staff=False,
    )
    c = APIClient()
    c.force_authenticate(user=non_staff)

    r = c.get(reverse("v1:ops-stats"))
    assert r.status_code == 403


@pytest.mark.django_db
def test_ops_stats_room_counts_active_hidden_deleted_total_match_rules():
    admin = User.objects.create_user(
        username="admin_rooms",
        password="pass123",
        email="admin_rooms@example.com",
        is_staff=True,
    )
    c = APIClient()
    c.force_authenticate(user=admin)
    url = reverse("v1:ops-stats")

    cat = RoomCategorie.objects.create(name="Cat A")

    # 1 active (not deleted)
    Room.objects.create(
        title="Active room",
        description="desc",
        price_per_month="500.00",
        location="London",
        category=cat,
        property_owner=admin,
        status="active",
    )

    # 1 hidden (not deleted)
    Room.objects.create(
        title="Hidden room",
        description="desc",
        price_per_month="600.00",
        location="London",
        category=cat,
        property_owner=admin,
        status="hidden",
    )

    # 1 deleted (still counts in total, counts in deleted, does not count in active/hidden because is_deleted=True)
    deleted_room = Room.objects.create(
        title="Deleted room",
        description="desc",
        price_per_month="700.00",
        location="London",
        category=cat,
        property_owner=admin,
        status="active",
    )
    deleted_room.is_deleted = True
    deleted_room.save(update_fields=["is_deleted"])

    r = c.get(url)
    data = _unwrap_ops_stats_response(r)

    assert data["listings"]["total"] == 3
    assert data["listings"]["active"] == 1
    assert data["listings"]["hidden"] == 1
    assert data["listings"]["deleted"] == 1


@pytest.mark.django_db
def test_ops_stats_payments_last_30_days_counts_only_succeeded_and_only_within_window():
    admin = User.objects.create_user(
        username="admin_payments",
        password="pass123",
        email="admin_payments@example.com",
        is_staff=True,
    )
    c = APIClient()
    c.force_authenticate(user=admin)
    url = reverse("v1:ops-stats")

    cat = RoomCategorie.objects.create(name="Cat Pay")
    room = Room.objects.create(
        title="Room",
        description="desc",
        price_per_month="500.00",
        location="London",
        category=cat,
        property_owner=admin,
        status="active",
    )

    now = timezone.now()

    # succeeded within 30 days -> included
    p1 = Payment.objects.create(user=admin, room=room, amount="2.00", currency="GBP", status="succeeded")
    Payment.objects.filter(pk=p1.pk).update(created_at=now - timedelta(days=5))

    # succeeded but older than 30 days -> excluded
    p2 = Payment.objects.create(user=admin, room=room, amount="3.00", currency="GBP", status="succeeded")
    Payment.objects.filter(pk=p2.pk).update(created_at=now - timedelta(days=40))

    # not succeeded within 30 days -> excluded
    p3 = Payment.objects.create(user=admin, room=room, amount="4.00", currency="GBP", status="created")
    Payment.objects.filter(pk=p3.pk).update(created_at=now - timedelta(days=2))

    r = c.get(url)
    data = _unwrap_ops_stats_response(r)

    assert data["payments"]["last_30_days"]["count"] == 1

    gross = data["payments"]["last_30_days"]["sum_gbp"]
    if isinstance(gross, str):
        assert gross in {"2", "2.0", "2.00"}
    else:
        assert float(gross) == 2.0