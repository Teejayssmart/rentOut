import pytest
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from propertylist_app.models import Booking, Room, Review


pytestmark = pytest.mark.django_db


def make_user(email="u@example.com", password="pass12345", username=None):
    User = get_user_model()
    if username is None:
        username = email.split("@")[0]
    return User.objects.create_user(username=username, email=email, password=password)



def make_room(owner, title="Room 1", price_per_month=800):
    """
    Add any other required Room fields here once, and all tests will pass.
    """
    return Room.objects.create(
        property_owner=owner,
        title=title,
        price_per_month=price_per_month,
    )



def make_booking(room, tenant, end_dt):
    """
    Adjust fields here if your Booking model has required fields.
    The important part for these tests is: booking.user, booking.room, booking.end
    """
    start_dt = end_dt - timedelta(days=30)
    return Booking.objects.create(room=room, user=tenant, start=start_dt, end=end_dt)


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def booking_create_url(booking_id):
    return f"/api/bookings/{booking_id}/reviews/create/"


def booking_list_url(booking_id):
    return f"/api/bookings/{booking_id}/reviews/"


def test_cannot_review_before_booking_ends():
    landlord = make_user("landlord@example.com")
    tenant = make_user("tenant@example.com")
    room = make_room(owner=landlord)
    booking = make_booking(room=room, tenant=tenant, end_dt=timezone.now() + timedelta(days=2))

    client = auth_client(tenant)
    res = client.post(
        booking_create_url(booking.id),
        data={"review_flags": ["responsive"], "notes": "ok"},
        format="json",
    )
    assert res.status_code == 400



def test_cannot_review_after_30_day_window():
    landlord = make_user("landlord3@example.com")
    tenant = make_user("tenant3@example.com")
    room = make_room(owner=landlord)
    booking = make_booking(room=room, tenant=tenant, end_dt=timezone.now() - timedelta(days=31))

    client = auth_client(tenant)
    res = client.post(
        booking_create_url(booking.id),
        data={"review_flags": ["responsive"], "notes": "late"},
        format="json",
    )
    assert res.status_code == 400


def test_random_user_cannot_review_booking():
    landlord = make_user("landlord4@example.com")
    tenant = make_user("tenant4@example.com")
    stranger = make_user("stranger@example.com")
    room = make_room(owner=landlord)
    booking = make_booking(room=room, tenant=tenant, end_dt=timezone.now() - timedelta(days=1))

    client = auth_client(stranger)
    res = client.post(
        booking_create_url(booking.id),
        data={"review_flags": ["responsive"], "notes": "hmm"},
        format="json",
    )
    assert res.status_code == 400


def test_booking_review_endpoint_is_blocked_even_if_called_twice():
    landlord = make_user("landlord5@example.com")
    tenant = make_user("tenant5@example.com")
    room = make_room(owner=landlord)
    booking = make_booking(room=room, tenant=tenant, end_dt=timezone.now() - timedelta(days=2))

    client = auth_client(tenant)

    res1 = client.post(
        booking_create_url(booking.id),
        data={"review_flags": ["responsive"], "notes": "first"},
        format="json",
    )
    assert res1.status_code == 400

    res2 = client.post(
        booking_create_url(booking.id),
        data={"review_flags": ["responsive"], "notes": "second"},
        format="json",
    )
    assert res2.status_code == 400

    # Optional: ensure the reason is the same rule (booking/viewing reviews disabled)
    assert "booking/viewing reviews are disabled" in str(res1.data).lower()
    assert "booking/viewing reviews are disabled" in str(res2.data).lower()



def test_whitelist_rejects_unknown_flag():
    landlord = make_user("landlord6@example.com")
    tenant = make_user("tenant6@example.com")
    room = make_room(owner=landlord)
    booking = make_booking(room=room, tenant=tenant, end_dt=timezone.now() - timedelta(days=2))

    client = auth_client(tenant)
    res = client.post(
        booking_create_url(booking.id),
        data={"review_flags": ["hack_flag"], "notes": "nope"},
        format="json",
    )
    assert res.status_code == 400


def test_booking_review_double_blind_logic_not_applicable_because_booking_reviews_disabled():
    landlord = make_user("landlord7@example.com")
    tenant = make_user("tenant7@example.com")
    room = make_room(owner=landlord)
    booking = make_booking(room=room, tenant=tenant, end_dt=timezone.now() - timedelta(days=2))

    tenant_client = auth_client(tenant)
    landlord_client = auth_client(landlord)

    res_tenant = tenant_client.post(
        booking_create_url(booking.id),
        data={"review_flags": ["responsive"], "notes": "tenant review"},
        format="json",
    )
    res_landlord = landlord_client.post(
        booking_create_url(booking.id),
        data={"review_flags": ["responsive"], "notes": "landlord review"},
        format="json",
    )

    assert res_tenant.status_code == 400
    assert res_landlord.status_code == 400
    assert "booking/viewing reviews are disabled" in str(res_tenant.data).lower()
    assert "booking/viewing reviews are disabled" in str(res_landlord.data).lower()



def test_cannot_review_booking_even_after_booking_end():
    landlord = make_user("landlord2@example.com")
    tenant = make_user("tenant2@example.com")
    room = make_room(owner=landlord)
    booking = make_booking(room=room, tenant=tenant, end_dt=timezone.now() - timedelta(days=5))

    client = auth_client(tenant)
    res = client.post(
        booking_create_url(booking.id),
        data={"review_flags": ["responsive"], "notes": "good"},
        format="json",
    )

    assert res.status_code == 400
    assert "booking/viewing reviews are disabled" in str(res.data).lower()
