import pytest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from propertylist_app.models import (
    Booking,
    Message,
    Notification,
    Room,
    RoomCategorie,
    UserProfile,
)
from propertylist_app.services.tasks import notify_upcoming_bookings
from notifications.models import NotificationTemplate, OutboundNotification

pytestmark = pytest.mark.django_db


def _mk_category(name="Test Category"):
    return RoomCategorie.objects.create(name=name, active=True)


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
    category = _mk_category("Booking Reminder A")

    room = Room.objects.create(
        title="Room A",
        property_owner=user,
        category=category,
        price_per_month=1000,
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_reminders = True
    profile.save(update_fields=["notify_reminders"])

    start = timezone.now() + timedelta(minutes=4)
    _mk_booking(user, room, start=start)

    notify_upcoming_bookings(5)

    assert Notification.objects.filter(user=user, type="booking_reminder").count() == 1


def test_notify_upcoming_bookings_skips_when_notify_reminders_off():
    User = get_user_model()
    user = User.objects.create_user(username="u2", password="pass12345")
    category = _mk_category("Booking Reminder B")

    room = Room.objects.create(
        title="Room B",
        property_owner=user,
        category=category,
        price_per_month=1000,
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_reminders = False
    profile.save(update_fields=["notify_reminders"])

    start = timezone.now() + timedelta(minutes=4)
    _mk_booking(user, room, start=start)

    notify_upcoming_bookings(5)

    assert Notification.objects.filter(user=user, type="booking_reminder").count() == 0


def test_notify_upcoming_bookings_skips_cancelled_bookings():
    User = get_user_model()
    user = User.objects.create_user(username="u3", password="pass12345")
    category = _mk_category("Booking Reminder C")

    room = Room.objects.create(
        title="Room C",
        property_owner=user,
        category=category,
        price_per_month=1000,
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_reminders = True
    profile.save(update_fields=["notify_reminders"])

    start = timezone.now() + timedelta(minutes=4)
    _mk_booking(user, room, start=start, cancelled=True)

    notify_upcoming_bookings(5)

    assert Notification.objects.filter(user=user, type="booking_reminder").count() == 0


def test_notify_upcoming_bookings_skips_deleted_bookings():
    User = get_user_model()
    user = User.objects.create_user(username="u4", password="pass12345")
    category = _mk_category("Booking Reminder D")

    room = Room.objects.create(
        title="Room D",
        property_owner=user,
        category=category,
        price_per_month=1000,
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_reminders = True
    profile.save(update_fields=["notify_reminders"])

    start = timezone.now() + timedelta(minutes=4)
    _mk_booking(user, room, start=start, deleted=True)

    notify_upcoming_bookings(5)

    assert Notification.objects.filter(user=user, type="booking_reminder").count() == 0


def test_notify_upcoming_bookings_no_duplicates_on_repeat_runs():
    User = get_user_model()
    user = User.objects.create_user(username="u5", password="pass12345")
    category = _mk_category("Booking Reminder E")

    room = Room.objects.create(
        title="Room E",
        property_owner=user,
        category=category,
        price_per_month=1000,
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_reminders = True
    profile.save(update_fields=["notify_reminders"])

    start = timezone.now() + timedelta(minutes=4)
    _mk_booking(user, room, start=start)

    notify_upcoming_bookings(5)
    notify_upcoming_bookings(5)

    assert Notification.objects.filter(user=user, type="booking_reminder").count() == 1
    
    
    
    
def test_upcoming_viewing_reminds_both_seeker_and_landlord():
    User = get_user_model()

    landlord = User.objects.create_user(
        username="landlord-reminder",
        first_name="Landlord",
        password="pass12345",
    )

    seeker = User.objects.create_user(
        username="seeker-reminder",
        first_name="Seeker",
        password="pass12345",
    )

    category = _mk_category("Dual Reminder")

    room = Room.objects.create(
        title="Dual Reminder Room",
        property_owner=landlord,
        category=category,
        price_per_month=1000,
    )

    for user in (landlord, seeker):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.notify_reminders = True
        profile.save(update_fields=["notify_reminders"])

    NotificationTemplate.objects.create(
        key="booking.reminder",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Seeker reminder",
        body="x",
        is_active=True,
    )

    NotificationTemplate.objects.create(
        key="booking.reminder_landlord",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Landlord reminder",
        body="x",
        is_active=True,
    )

    start = timezone.now() + timedelta(minutes=4)
    booking = _mk_booking(seeker, room, start=start)

    notify_upcoming_bookings(5)

    assert Notification.objects.filter(
        user=seeker,
        type="booking_reminder",
    ).count() == 1

    assert Notification.objects.filter(
        user=landlord,
        type="booking_reminder_landlord",
    ).count() == 1

    assert OutboundNotification.objects.filter(
        user=seeker,
        template_key="booking.reminder",
        context__booking_id=booking.id,
    ).count() == 1


    seeker_email = OutboundNotification.objects.get(
        user=seeker,
        template_key="booking.reminder",
        context__booking_id=booking.id,
    )

    assert f"/viewings/{booking.id}" in seeker_email.context["cta_url"]
    assert "/login?next=" not in seeker_email.context["cta_url"]

    landlord_email = OutboundNotification.objects.get(
        user=landlord,
        template_key="booking.reminder_landlord",
        context__booking_id=booking.id,
    )

    assert landlord_email.context["booker"]["name"] == "Seeker"
    assert f"/viewings/{booking.id}" in landlord_email.context["cta_url"]


def test_upcoming_viewing_creates_one_shared_system_message():
    User = get_user_model()

    landlord = User.objects.create_user(
        username="landlord-system",
        password="pass12345",
    )

    seeker = User.objects.create_user(
        username="seeker-system",
        password="pass12345",
    )

    category = _mk_category("System Reminder")

    room = Room.objects.create(
        title="System Reminder Room",
        property_owner=landlord,
        category=category,
        price_per_month=1000,
    )

    for user in (landlord, seeker):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.notify_reminders = True
        profile.save(update_fields=["notify_reminders"])

    start = timezone.now() + timedelta(minutes=4)
    booking = _mk_booking(seeker, room, start=start)

    notify_upcoming_bookings(5)
    notify_upcoming_bookings(5)

    messages = Message.objects.filter(
        metadata__system_event=True,
        metadata__event_type="booking_reminder",
        metadata__booking_id=booking.id,
    )

    assert messages.count() == 1

    message = messages.get()

    assert set(
        message.thread.participants.values_list("id", flat=True)
    ) == {landlord.id, seeker.id}


def test_rescheduled_viewing_can_create_fresh_system_reminder():
    User = get_user_model()

    landlord = User.objects.create_user(
        username="landlord-reschedule",
        password="pass12345",
    )

    seeker = User.objects.create_user(
        username="seeker-reschedule",
        password="pass12345",
    )

    category = _mk_category("Reschedule Reminder")

    room = Room.objects.create(
        title="Rescheduled Reminder Room",
        property_owner=landlord,
        category=category,
        price_per_month=1000,
    )

    for user in (landlord, seeker):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.notify_reminders = True
        profile.save(update_fields=["notify_reminders"])

    first_start = timezone.now() + timedelta(minutes=4)
    booking = _mk_booking(seeker, room, start=first_start)

    notify_upcoming_bookings(5)

    second_start = timezone.now() + timedelta(minutes=3)
    booking.start = second_start
    booking.end = second_start + timedelta(hours=1)
    booking.save(update_fields=["start", "end"])

    notify_upcoming_bookings(5)

    assert Message.objects.filter(
        metadata__system_event=True,
        metadata__event_type="booking_reminder",
        metadata__booking_id=booking.id,
    ).count() == 2    