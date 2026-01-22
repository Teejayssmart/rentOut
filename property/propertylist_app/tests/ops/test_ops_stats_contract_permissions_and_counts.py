import pytest
from datetime import timedelta

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, Payment


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
    assert r.status_code == 200, r.data
    data = r.json()

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
    for k in ["total", "active", "hidden", "deleted"]:
        assert isinstance(data["listings"][k], int)

    # users
    assert set(data["users"].keys()) == {"total"}
    assert (data["users"]["total"] is None) or isinstance(data["users"]["total"], int)

    # bookings
    assert set(data["bookings"].keys()) == {"last_7_days", "last_30_days", "upcoming_viewings"}
    for k in ["last_7_days", "last_30_days", "upcoming_viewings"]:
        assert isinstance(data["bookings"][k], int)

    # payments
    assert set(data["payments"].keys()) == {"last_30_days"}
    assert set(data["payments"]["last_30_days"].keys()) == {"count", "sum_gbp"}
    assert isinstance(data["payments"]["last_30_days"]["count"], int)
    assert isinstance(data["payments"]["last_30_days"]["sum_gbp"], (int, float))

    # messages
    assert set(data["messages"].keys()) == {"last_7_days", "threads_total"}
    assert isinstance(data["messages"]["last_7_days"], int)
    assert isinstance(data["messages"]["threads_total"], int)

    # reports
    assert set(data["reports"].keys()) == {"open", "in_review"}
    assert isinstance(data["reports"]["open"], int)
    assert isinstance(data["reports"]["in_review"], int)

    # categories
    assert set(data["categories"].keys()) == {"top_active"}
    assert isinstance(data["categories"]["top_active"], list)
    for item in data["categories"]["top_active"]:
        assert set(item.keys()) == {"id", "name", "count"}
        assert isinstance(item["count"], int)


@pytest.mark.django_db
def test_ops_stats_permissions_matrix_anonymous_regular_staff_superuser():
    url = reverse("v1:ops-stats")

    # anonymous -> 401
    anon = APIClient()
    r_anon = anon.get(url)
    assert r_anon.status_code == 401

    # regular authenticated -> 403
    regular = User.objects.create_user(username="ops_regular", password="pass123", email="ops_regular@example.com")
    c_reg = APIClient()
    c_reg.force_authenticate(user=regular)
    r_reg = c_reg.get(url)
    assert r_reg.status_code == 403

    # staff -> 200
    staff = User.objects.create_user(
        username="ops_staff",
        password="pass123",
        email="ops_staff@example.com",
        is_staff=True,
        is_superuser=False,
    )
    c_staff = APIClient()
    c_staff.force_authenticate(user=staff)
    r_staff = c_staff.get(url)
    assert r_staff.status_code == 200, r_staff.data

    # superuser -> 200
    superuser = User.objects.create_user(
        username="ops_super",
        password="pass123",
        email="ops_super@example.com",
        is_staff=True,
        is_superuser=True,
    )
    c_super = APIClient()
    c_super.force_authenticate(user=superuser)
    r_super = c_super.get(url)
    assert r_super.status_code == 200, r_super.data


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
    assert r.status_code == 200, r.data
    data = r.json()

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
    assert r.status_code == 200, r.data
    data = r.json()

    assert data["payments"]["last_30_days"]["count"] == 1
    assert data["payments"]["last_30_days"]["sum_gbp"] in (2.0, 2)  # view rounds to 2dp
