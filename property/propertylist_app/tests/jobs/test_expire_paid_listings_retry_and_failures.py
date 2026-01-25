import pytest
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from unittest.mock import patch

from propertylist_app.models import Room, RoomCategorie, UserProfile, Notification
from propertylist_app.services.tasks import expire_paid_listings


pytestmark = pytest.mark.django_db


def _mk_user(username="u1", email="u1@example.com"):
    User = get_user_model()
    return User.objects.create_user(username=username, password="pass12345", email=email)


def _mk_room(owner, *, title="Room", status="active", is_deleted=False, paid_until=None):
    cat = RoomCategorie.objects.create(name="Central", active=True)
    return Room.objects.create(
        title=title,
        description="word " * 30,
        price_per_month=900,
        security_deposit=200,
        location="London",
        category=cat,
        property_owner=owner,
        property_type="flat",
        status=status,
        is_deleted=is_deleted,
        paid_until=paid_until,
    )


def test_expire_paid_listings_hides_only_expired_active_rooms_and_returns_count():
    owner = _mk_user("owner1")
    today = timezone.localdate()

    expired = _mk_room(owner, title="Expired", status="active", paid_until=today - timedelta(days=1))
    not_expired = _mk_room(owner, title="NotExpired", status="active", paid_until=today + timedelta(days=1))
    already_hidden = _mk_room(owner, title="Hidden", status="hidden", paid_until=today - timedelta(days=1))
    deleted = _mk_room(owner, title="Deleted", status="active", is_deleted=True, paid_until=today - timedelta(days=1))

    updated = expire_paid_listings(today=today)
    assert updated == 1

    expired.refresh_from_db()
    not_expired.refresh_from_db()
    already_hidden.refresh_from_db()
    deleted.refresh_from_db()

    assert expired.status == "hidden"
    assert not_expired.status == "active"
    assert already_hidden.status == "hidden"
    assert deleted.status == "active"


def test_expire_paid_listings_respects_notify_reminders_toggle():
    owner = _mk_user("owner2")
    UserProfile.objects.get_or_create(user=owner)
    UserProfile.objects.filter(user=owner).update(notify_reminders=False)

    today = timezone.localdate()
    _mk_room(owner, title="Expired", status="active", paid_until=today - timedelta(days=1))

    updated = expire_paid_listings(today=today)
    assert updated == 1

    assert Notification.objects.filter(user=owner, type="listing_expired").count() == 0


def test_expire_paid_listings_notification_failure_does_not_block_hiding():
    owner = _mk_user("owner3")
    today = timezone.localdate()
    room = _mk_room(owner, title="Expired", status="active", paid_until=today - timedelta(days=1))

    # Force Notification.create to blow up
    with patch("propertylist_app.services.tasks.Notification.objects.create", side_effect=Exception("boom")):
        updated = expire_paid_listings(today=today)

    assert updated == 1
    room.refresh_from_db()
    assert room.status == "hidden"


def test_expire_paid_listings_running_twice_is_idempotent_second_run_updates_0():
    owner = _mk_user("owner4")
    today = timezone.localdate()
    room = _mk_room(owner, title="Expired", status="active", paid_until=today - timedelta(days=1))

    first = expire_paid_listings(today=today)
    second = expire_paid_listings(today=today)

    assert first == 1
    assert second == 0

    room.refresh_from_db()
    assert room.status == "hidden"
