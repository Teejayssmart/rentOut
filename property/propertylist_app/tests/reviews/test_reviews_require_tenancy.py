from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db

API_PREFIX = "/api/v1"


def _get_model(app_label, model_name):
    return apps.get_model(app_label, model_name)


def _api_client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_user(username: str):
    User = _get_model("auth", "User")
    return User.objects.create_user(
        username=username,
        password="pass12345",
        email=f"{username}@example.com",
    )


def _make_room(*, owner):
    Room = _get_model("propertylist_app", "Room")
    RoomCategorie = _get_model("propertylist_app", "RoomCategorie")

    category = RoomCategorie.objects.create(name=f"Cat-{owner.username}", active=True)
    return Room.objects.create(
        title=f"Room {owner.username}",
        description="A valid room description with enough words to satisfy validation rules.",
        price_per_month=750,
        location="London",
        category=category,
        property_owner=owner,
        property_type="flat",
    )


def _make_viewing_booking(user, room):
    Booking = _get_model("propertylist_app", "Booking")
    now = timezone.now()
    return Booking.objects.create(
        user=user,
        room=room,
        start=now - timedelta(days=3),
        end=now - timedelta(days=2),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )


def _make_tenancy(room, landlord, tenant, *, status, review_open_at, review_deadline_at):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    now = timezone.now()

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=3,
        status=status,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
        review_open_at=review_open_at,
        review_deadline_at=review_deadline_at,
    )
    return tenancy


def _booking_reviews_url(booking_id: int) -> str:
    return f"/bookings/{booking_id}/reviews/create/"


def _reviews_create_url() -> str:
    return f"{API_PREFIX}/reviews/create/"


def test_booking_review_create_is_blocked_as_viewing_flow():
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = _make_user("landlord_r1")
    tenant = _make_user("tenant_r1")
    room = _make_room(owner=landlord)
    booking = _make_viewing_booking(user=tenant, room=room)

    tenant_client = _api_client_for(tenant)

    resp = tenant_client.post(
        _booking_reviews_url(booking.id),
        data={"review_flags": ["responsive"]},
        format="json",
    )

    assert resp.status_code in (400, 404, 405), getattr(resp, "data", None)


def test_tenancy_review_is_blocked_before_review_open_at():
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")
    now = timezone.now()

    landlord = _make_user("landlord_r2")
    tenant = _make_user("tenant_r2")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    tenancy = _make_tenancy(
        room,
        landlord,
        tenant,
        status=Tenancy.STATUS_ENDED,
        review_open_at=now + timedelta(days=2),
        review_deadline_at=now + timedelta(days=30),
    )

    tenant_client = _api_client_for(tenant)

    payload = {
        "tenancy_id": tenancy.id,
        "role": Review.ROLE_TENANT_TO_LANDLORD,
        "overall_rating": 4,
        "notes": "Trying too early",
    }

    resp = tenant_client.post(_reviews_create_url(), data=payload, format="json")
    assert resp.status_code == 400, getattr(resp, "data", None)


def test_tenancy_review_succeeds_after_review_open_at_and_blocks_duplicates():
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")
    now = timezone.now()

    landlord = _make_user("landlord_r3")
    tenant = _make_user("tenant_r3")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    tenancy = _make_tenancy(
        room,
        landlord,
        tenant,
        status=Tenancy.STATUS_ENDED,
        review_open_at=now - timedelta(days=1),
        review_deadline_at=now + timedelta(days=30),
    )

    tenant_client = _api_client_for(tenant)

    payload = {
        "tenancy_id": tenancy.id,
        "role": Review.ROLE_TENANT_TO_LANDLORD,
        "overall_rating": 5,
        "notes": "Great landlord",
    }

    resp1 = tenant_client.post(_reviews_create_url(), data=payload, format="json")
    assert resp1.status_code == 201, getattr(resp1, "data", None)

    created = Review.objects.get(
        tenancy=tenancy,
        reviewer=tenant,
        role=Review.ROLE_TENANT_TO_LANDLORD,
    )
    assert created.reviewee_id == landlord.id
    assert int(created.overall_rating) == 5

    resp2 = tenant_client.post(_reviews_create_url(), data=payload, format="json")
    assert resp2.status_code == 400, getattr(resp2, "data", None)