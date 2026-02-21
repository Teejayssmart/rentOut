import pytest
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from rest_framework.test import APIClient

from propertylist_app.models import RoomCategorie, Room, Booking, Review

# IMPORTANT: once you add Tenancy model, this import must work
from propertylist_app.models import Tenancy


pytestmark = pytest.mark.django_db

API_PREFIX = "/api/v1"


def _api_client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_user(username: str):
    User = get_user_model()
    return User.objects.create_user(
        username=username,
        password="pass12345",
        email=f"{username}@example.com",
    )


def _make_room(owner):
    cat = RoomCategorie.objects.create(name="Standard")
    return Room.objects.create(
        title="Nice room",
        description="Clean room",
        price_per_month="500.00",
        location="Southampton",
        category=cat,
        furnished=False,
        bills_included=False,
        property_owner=owner,
        property_type="flat",
    )


def _make_viewing_booking(user, room):
    now = timezone.now()
    return Booking.objects.create(
        user=user,
        room=room,
        start=now + timedelta(days=2),
        end=now + timedelta(days=2, hours=1),
    )


def test_booking_review_create_is_blocked_as_viewing_flow():
    landlord = _make_user("landlord_r1")
    tenant = _make_user("tenant_r1")
    room = _make_room(owner=landlord)
    booking = _make_viewing_booking(user=tenant, room=room)

    tenant_client = _api_client_for(tenant)

    resp = tenant_client.post(
        f"{API_PREFIX}/bookings/{booking.id}/reviews/create/",
        data={"review_flags": ["responsive"]},
        format="json",
    )

    # You will enforce: "booking reviews disabled"
    assert resp.status_code == 400
    msg = str(resp.data)
    assert "booking" in msg.lower()
    assert "disabled" in msg.lower() or "tenancy" in msg.lower()


def test_tenancy_review_is_blocked_before_review_open_at():
    landlord = _make_user("landlord_r2")
    tenant = _make_user("tenant_r2")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    # create a tenancy with review_open_at in the future
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() + timedelta(days=3),
        duration_months=6,
        status=Tenancy.STATUS_CONFIRMED,
        landlord_confirmed_at=timezone.now(),
        tenant_confirmed_at=timezone.now(),
        review_open_at=timezone.now() + timedelta(days=30),
        still_living_check_at=timezone.now() + timedelta(days=10),
    )

    tenant_client = _api_client_for(tenant)
    resp = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy.id}/reviews/",
        data={"review_flags": ["responsive"]},
        format="json",
    )

    assert resp.status_code == 400
    assert "after" in str(resp.data).lower() or "tenancy" in str(resp.data).lower()


def test_tenancy_review_succeeds_after_review_open_at_and_blocks_duplicates():
    landlord = _make_user("landlord_r3")
    tenant = _make_user("tenant_r3")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    # Make review_open_at in the past so review is allowed now
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=70),
        duration_months=2,
        status=Tenancy.STATUS_CONFIRMED,
        landlord_confirmed_at=timezone.now() - timedelta(days=80),
        tenant_confirmed_at=timezone.now() - timedelta(days=80),
        review_open_at=timezone.now() - timedelta(days=1),
        still_living_check_at=timezone.now() - timedelta(days=20),
    )

    tenant_client = _api_client_for(tenant)

    # First submission should succeed
    resp1 = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy.id}/reviews/",
        data={"review_flags": ["responsive", "maintenance_good"]},
        format="json",
    )
    assert resp1.status_code == 201, resp1.data

    assert Review.objects.filter(tenancy=tenancy, reviewer=tenant).exists()

    review = Review.objects.get(tenancy=tenancy, reviewer=tenant)
    assert review.role == Review.ROLE_TENANT_TO_LANDLORD
    assert review.reviewee_id == landlord.id

    # Duplicate submission (same role) should fail
    resp2 = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy.id}/reviews/",
        data={"review_flags": ["responsive"]},
        format="json",
    )
    assert resp2.status_code == 400
    assert "already" in str(resp2.data).lower() or "submitted" in str(resp2.data).lower()


def test_tenancy_review_is_blocked_after_review_deadline_at():
    landlord = _make_user("landlord_r_deadline")
    tenant = _make_user("tenant_r_deadline")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=120),
        duration_months=3,
        status=Tenancy.STATUS_CONFIRMED,
        landlord_confirmed_at=timezone.now() - timedelta(days=120),
        tenant_confirmed_at=timezone.now() - timedelta(days=120),
        # open in the past but deadline also in the past
        review_open_at=timezone.now() - timedelta(days=30),
        review_deadline_at=timezone.now() - timedelta(days=1),
        still_living_check_at=timezone.now() - timedelta(days=60),
    )

    tenant_client = _api_client_for(tenant)
    resp = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy.id}/reviews/",
        data={"review_flags": ["responsive"]},
        format="json",
    )

    assert resp.status_code == 400
    msg = str(resp.data).lower()
    assert "deadline" in msg or "passed" in msg or "late" in msg


def test_tenancy_review_is_blocked_after_review_deadline_at():
    landlord = _make_user("landlord_r_deadline")
    tenant = _make_user("tenant_r_deadline")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=120),
        duration_months=3,
        status=Tenancy.STATUS_CONFIRMED,
        landlord_confirmed_at=timezone.now() - timedelta(days=120),
        tenant_confirmed_at=timezone.now() - timedelta(days=120),
        review_open_at=timezone.now() - timedelta(days=30),
        review_deadline_at=timezone.now() - timedelta(days=1),
        still_living_check_at=timezone.now() - timedelta(days=60),
    )

    tenant_client = _api_client_for(tenant)
    resp = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy.id}/reviews/",
        data={"review_flags": ["responsive"], "notes": "too late"},
        format="json",
    )

    assert resp.status_code == 400
    msg = str(resp.data).lower()
    assert "expired" in msg or "window" in msg or "deadline" in msg



def test_random_user_cannot_review_tenancy():
    landlord = _make_user("landlord_r_stranger")
    tenant = _make_user("tenant_r_stranger")
    stranger = _make_user("stranger_r_stranger")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=3,
        status=Tenancy.STATUS_CONFIRMED,
        landlord_confirmed_at=timezone.now() - timedelta(days=90),
        tenant_confirmed_at=timezone.now() - timedelta(days=90),
        review_open_at=timezone.now() - timedelta(days=10),
        review_deadline_at=timezone.now() + timedelta(days=10),
    )

    stranger_client = _api_client_for(stranger)
    resp = stranger_client.post(
        f"{API_PREFIX}/tenancies/{tenancy.id}/reviews/",
        data={"review_flags": ["responsive"], "notes": "i should not be allowed"},
        format="json",
    )

    assert resp.status_code in (400, 403, 404)



def test_tenancy_review_is_blocked_if_tenancy_not_eligible_yet():
    landlord = _make_user("landlord_r_noteligible")
    tenant = _make_user("tenant_r_noteligible")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() + timedelta(days=10),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,  # not eligible
        landlord_confirmed_at=timezone.now(),
        tenant_confirmed_at=None,
        review_open_at=timezone.now() - timedelta(days=1),  # even if open, status should block
    )

    tenant_client = _api_client_for(tenant)
    resp = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy.id}/reviews/",
        data={"review_flags": ["responsive"], "notes": "should be blocked"},
        format="json",
    )

    assert resp.status_code == 400
    msg = str(resp.data).lower()
    assert "eligible" in msg or "tenancy" in msg or "confirmed" in msg or "proposed" in msg
