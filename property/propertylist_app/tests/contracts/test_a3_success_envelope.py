import pytest
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import RoomCategorie, Room, MessageThread, Message, Booking

pytestmark = pytest.mark.django_db


def _authed_client():
    User = get_user_model()
    u = User.objects.create_user(
        username="a3user",
        password="pass123",
        email="a3user@test.com",
    )
    c = APIClient()
    c.force_authenticate(user=u)
    return c, u


def _assert_ok_envelope(resp):
    # reason: A3 rule for success responses is ok + data
    assert resp.status_code in (200, 201), getattr(resp, "content", b"")
    assert isinstance(resp.data, dict), resp.data
    assert resp.data.get("ok") is True, resp.data
    assert "data" in resp.data, resp.data


def test_a3_homepage_returns_ok_envelope():
    c = APIClient()

    # reason: avoid reverse() naming issues; assert the real integration path
    r = c.get("/api/home/")
    _assert_ok_envelope(r)


def test_a3_thread_mark_read_returns_ok_envelope():
    c, u = _authed_client()

    # reason: thread must include the authenticated user as a participant
    thread = MessageThread.objects.create()
    thread.participants.add(u)

    # reason: your Message model uses "body" (not "content")
    Message.objects.create(thread=thread, sender=u, body="hi")

    r = c.post(f"/api/messages/threads/{thread.id}/read/", {}, format="json")
    _assert_ok_envelope(r)


def test_a3_booking_cancel_returns_ok_envelope():
    c, u = _authed_client()

    cat = RoomCategorie.objects.create(name="A3Cat", active=True)
    owner = get_user_model().objects.create_user(
        username="a3owner",
        password="pass123",
        email="a3owner@test.com",
    )

    room = Room.objects.create(
        title="A3 Room",
        category=cat,
        price_per_month=100,
        property_owner=owner,
    )

    # reason: Booking.start/end are required (NOT NULL)
    start = timezone.now() + timedelta(days=2)
    end = start + timedelta(hours=1)

    booking = Booking.objects.create(
        user=u,
        room=room,
        start=start,
        end=end,
        status="active",
    )

    r = c.post(f"/api/bookings/{booking.id}/cancel/", {}, format="json")
    _assert_ok_envelope(r)


def test_a3_room_save_toggle_returns_ok_envelope():
    c, u = _authed_client()

    cat = RoomCategorie.objects.create(name="A3Cat2", active=True)
    owner = get_user_model().objects.create_user(
        username="a3owner2",
        password="pass123",
        email="a3owner2@test.com",
    )

    room = Room.objects.create(
        title="A3 Room 2",
        category=cat,
        price_per_month=200,
        property_owner=owner,
    )

    r = c.post(f"/api/rooms/{room.id}/save-toggle/", {}, format="json")
    _assert_ok_envelope(r)
