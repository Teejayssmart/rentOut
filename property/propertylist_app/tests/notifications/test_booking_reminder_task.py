import pytest
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model

from propertylist_app.models import Booking, Room, UserProfile, Notification
from propertylist_app.services.tasks import notify_upcoming_bookings


pytestmark = pytest.mark.django_db


def _mk_booking(user, room, start, end=None, *, cancelled=False, deleted=False):
    if end is None:
        end = start + timedelta(hours=1)
    booking = Booking.objects.create(user=user, room=room, start=start, end=end)
    if cancelled:
        booking.canceled_at = timezone.now()
        booking.save(update_fields=["canceled_at"])
    if deleted:
        booking.is_deleted = True
        booking.deleted_at = timezone.now()
        booking.save(update_fields=["is_deleted", "deleted_at"])
    return booking


def test_notify_upcoming_bookings_creates_notification_when_in_window_and_opted_in():
    User = get_user_model()
    user = User.objects.create_user(username="u1", password="pass12345")
    room = Room.objects.create(title="Room A", property_owner=user, price_per_month=1000)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_reminders = True
    profile.save(update_fields=["notify_reminders"])

    start = timezone.now() + timedelta(hours=2)
    _mk_booking(user, room, start=start)

    notify_upcoming_bookings(24)

    assert Notification.objects.filter(user=user, type="booking_reminder").count() == 1


def test_notify_upcoming_bookings_skips_when_notify_reminders_off():
    User = get_user_model()
    user = User.objects.create_user(username="u2", password="pass12345")
    room = Room.objects.create(title="Room B", property_owner=user, price_per_month=1000)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_reminders = False
    profile.save(update_fields=["notify_reminders"])

    start = timezone.now() + timedelta(hours=2)
    _mk_booking(user, room, start=start)

    notify_upcoming_bookings(24)

    assert Notification.objects.filter(user=user, type="booking_reminder").count() == 0


def test_notify_upcoming_bookings_skips_cancelled_bookings():
    User = get_user_model()
    user = User.objects.create_user(username="u3", password="pass12345")
    room = Room.objects.create(title="Room C", property_owner=user, price_per_month=1000)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_reminders = True
    profile.save(update_fields=["notify_reminders"])

    start = timezone.now() + timedelta(hours=2)
    _mk_booking(user, room, start=start, cancelled=True)

    notify_upcoming_bookings(24)

    assert Notification.objects.filter(user=user, type="booking_reminder").count() == 0


def test_notify_upcoming_bookings_skips_deleted_bookings():
    User = get_user_model()
    user = User.objects.create_user(username="u4", password="pass12345")
    room = Room.objects.create(title="Room D", property_owner=user, price_per_month=1000)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_reminders = True
    profile.save(update_fields=["notify_reminders"])

    start = timezone.now() + timedelta(hours=2)
    _mk_booking(user, room, start=start, deleted=True)

    notify_upcoming_bookings(24)

    assert Notification.objects.filter(user=user, type="booking_reminder").count() == 0


def test_notify_upcoming_bookings_no_duplicates_on_repeat_runs():
    User = get_user_model()
    user = User.objects.create_user(username="u5", password="pass12345")
    room = Room.objects.create(title="Room E", property_owner=user, price_per_month=1000)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_reminders = True
    profile.save(update_fields=["notify_reminders"])

    start = timezone.now() + timedelta(hours=2)
    _mk_booking(user, room, start=start)

    notify_upcoming_bookings(24)
    notify_upcoming_bookings(24)

    assert Notification.objects.filter(user=user, type="booking_reminder").count() == 1
