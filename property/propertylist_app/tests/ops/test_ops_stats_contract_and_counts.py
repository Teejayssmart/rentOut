from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import RoomCategorie, Room, Payment, Booking


pytestmark = pytest.mark.django_db


def _mk_user(username: str, *, is_staff: bool = False, is_superuser: bool = False):
    User = get_user_model()
    return User.objects.create_user(
        username=username,
        password="pass12345",
        is_staff=is_staff,
        is_superuser=is_superuser,
    )


def _auth_client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _mk_category(name="General"):
    # key auto-derived in save() if empty :contentReference[oaicite:3]{index=3}
    return RoomCategorie.objects.create(name=name, active=True)


def _mk_room(*, owner, category, status="active", is_deleted=False, title="Room A"):
    return Room.objects.create(
        title=title,
        description="word " * 30,
        price_per_month=Decimal("950.00"),
        security_deposit=Decimal("200.00"),
        location="London",
        category=category,
        property_owner=owner,
        property_type="flat",  # required (no default) :contentReference[oaicite:4]{index=4}
        status=status,
        is_deleted=is_deleted,
    )


def _mk_payment(*, user, room, status="succeeded", amount=Decimal("10.00"), created_at=None):
    p = Payment.objects.create(
        user=user,
        room=room,
        amount=amount,
        currency="GBP",
        status=status,
    )
    if created_at is not None:
        Payment.objects.filter(pk=p.pk).update(created_at=created_at)
        p.refresh_from_db()
    return p


def _mk_booking(*, user, room, start_dt, end_dt, created_at=None, canceled_at=None):
    b = Booking.objects.create(
        user=user,
        room=room,
        start=start_dt,
        end=end_dt,
        canceled_at=canceled_at,
    )
    if created_at is not None:
        Booking.objects.filter(pk=b.pk).update(created_at=created_at)
        b.refresh_from_db()
    return b


def test_ops_stats_schema_contract_exact_keys_and_types():
    admin = _mk_user("admin", is_staff=True)
    client = _auth_client(admin)

    url = "/api/v1/ops/stats/"
    res = client.get(url)
    assert res.status_code == 200
    data = res.json()

    # top-level keys (exact)
    assert set(data.keys()) == {
        "listings", "users", "bookings", "payments", "messages", "reports", "categories"
    }

    # listings
    assert set(data["listings"].keys()) == {"total", "active", "hidden", "deleted"}
    for k in ("total", "active", "hidden", "deleted"):
        assert isinstance(data["listings"][k], int)

    # users
    assert set(data["users"].keys()) == {"total"}
    assert (data["users"]["total"] is None) or isinstance(data["users"]["total"], int)

    # bookings
    assert set(data["bookings"].keys()) == {"last_7_days", "last_30_days", "upcoming_viewings"}
    for k in ("last_7_days", "last_30_days", "upcoming_viewings"):
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
    for row in data["categories"]["top_active"]:
        assert set(row.keys()) == {"id", "name", "count"}
        assert isinstance(row["count"], int)


def test_ops_stats_permissions_matrix():
    url = "/api/v1/ops/stats/"


    normal = _mk_user("normal", is_staff=False)
    staff = _mk_user("staff", is_staff=True)
    superuser = _mk_user("root", is_staff=True, is_superuser=True)

    res_normal = _auth_client(normal).get(url)
    assert res_normal.status_code in (403, 401)

    res_staff = _auth_client(staff).get(url)
    assert res_staff.status_code == 200

    res_super = _auth_client(superuser).get(url)
    assert res_super.status_code == 200


def test_ops_stats_counts_rooms_and_payments_match_rules():
    admin = _mk_user("admin2", is_staff=True)
    owner = _mk_user("owner", is_staff=False)
    client = _auth_client(admin)

    cat = _mk_category("Cat A")
    room_active = _mk_room(owner=owner, category=cat, status="active", is_deleted=False, title="Active")
    room_hidden = _mk_room(owner=owner, category=cat, status="hidden", is_deleted=False, title="Hidden")
    room_deleted = _mk_room(owner=owner, category=cat, status="active", is_deleted=True, title="Deleted")

    now = timezone.now()
    within_30 = now - timezone.timedelta(days=5)
    outside_30 = now - timezone.timedelta(days=45)

    # ops view counts only payments with status="succeeded" and created_at >= last 30 days :contentReference[oaicite:5]{index=5}
    _mk_payment(user=owner, room=room_active, status="succeeded", amount=Decimal("10.00"), created_at=within_30)
    _mk_payment(user=owner, room=room_active, status="succeeded", amount=Decimal("7.50"), created_at=within_30)
    _mk_payment(user=owner, room=room_active, status="created", amount=Decimal("999.00"), created_at=within_30)   # should NOT count
    _mk_payment(user=owner, room=room_active, status="succeeded", amount=Decimal("20.00"), created_at=outside_30)  # should NOT count

    url = "/api/v1/ops/stats/"
    res = client.get(url)
    assert res.status_code == 200
    data = res.json()

    assert data["listings"]["total"] >= 3
    assert data["listings"]["active"] >= 1
    assert data["listings"]["hidden"] >= 1
    assert data["listings"]["deleted"] >= 1

    assert data["payments"]["last_30_days"]["count"] == 2
    assert data["payments"]["last_30_days"]["sum_gbp"] == 17.5


def test_ops_stats_bookings_windows_and_upcoming_viewings():
    admin = _mk_user("admin3", is_staff=True)
    user = _mk_user("booker", is_staff=False)
    owner = _mk_user("owner2", is_staff=False)

    cat = _mk_category("Cat B")
    room = _mk_room(owner=owner, category=cat, status="active", is_deleted=False, title="R")

    now = timezone.now()

    # within 7 days
    _mk_booking(
        user=user,
        room=room,
        start_dt=now + timezone.timedelta(days=2),
        end_dt=now + timezone.timedelta(days=2, hours=1),
        created_at=now - timezone.timedelta(days=2),
        canceled_at=None,
    )

    # within 30 days but older than 7 days
    _mk_booking(
        user=user,
        room=room,
        start_dt=now + timezone.timedelta(days=10),
        end_dt=now + timezone.timedelta(days=10, hours=1),
        created_at=now - timezone.timedelta(days=20),
        canceled_at=None,
    )

    # outside 30 days
    _mk_booking(
        user=user,
        room=room,
        start_dt=now + timezone.timedelta(days=40),
        end_dt=now + timezone.timedelta(days=40, hours=1),
        created_at=now - timezone.timedelta(days=60),
        canceled_at=None,
    )

    # upcoming but cancelled -> should NOT count
    _mk_booking(
        user=user,
        room=room,
        start_dt=now + timezone.timedelta(days=3),
        end_dt=now + timezone.timedelta(days=3, hours=1),
        created_at=now - timezone.timedelta(days=1),
        canceled_at=now,
    )

    res = _auth_client(admin).get("/api/v1/ops/stats/")
    assert res.status_code == 200
    data = res.json()

    assert data["bookings"]["last_7_days"] == 2
    assert data["bookings"]["last_30_days"] == 3
    assert data["bookings"]["upcoming_viewings"] == 3
