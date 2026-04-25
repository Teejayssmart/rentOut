from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def _get_model(app_label, model_name):
    return apps.get_model(app_label, model_name)


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

    category = RoomCategorie.objects.create(name=f"Calc-{owner.username}", active=True)
    return Room.objects.create(
        title=f"Room {owner.username}",
        description="A valid room description with enough words to satisfy validation rules.",
        price_per_month=750,
        location="London",
        category=category,
        property_owner=owner,
        property_type="flat",
    )


def _make_tenancy(room, landlord, tenant, *, status):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    now = timezone.now()

    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=3,
        status=status,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
        review_open_at=now - timedelta(days=1),
        review_deadline_at=now + timedelta(days=30),
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _reviews_create_url():
    return "/api/v1/reviews/create/"


def test_tenant_to_landlord_flags_auto_calculate_overall_rating():
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = _make_user("calc_landlord_1")
    tenant = _make_user("calc_tenant_1")
    room = _make_room(owner=landlord)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = _client(tenant)

    payload = {
        "tenancy_id": tenancy.id,
        "review_flags": ["responsive", "maintenance_good"],
    }

    res = client.post(_reviews_create_url(), data=payload, format="json")
    assert res.status_code == 201, getattr(res, "data", None)

    review = Review.objects.get(
        tenancy=tenancy,
        reviewer=tenant,
        role=Review.ROLE_TENANT_TO_LANDLORD,
    )
    assert review.reviewee_id == landlord.id
    assert int(review.overall_rating) == 5