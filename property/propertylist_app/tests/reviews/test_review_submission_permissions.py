from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def _get_model(app_label, model_name):
    return apps.get_model(app_label, model_name)


def _make_tenancy(room, landlord, tenant, *, status):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    now = timezone.now()

    t = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=3,
        status=status,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
    )

    if hasattr(t, "review_open_at"):
        t.review_open_at = now - timedelta(days=1)
    if hasattr(t, "review_deadline_at"):
        t.review_deadline_at = now + timedelta(days=7)
    t.save()

    return t


def _reviews_create_url():
    return "/api/v1/reviews/create/"


def test_tenant_payload_cannot_force_landlord_role(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rp_landlord1")
    tenant = user_factory(username="rp_tenant1")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    client.force_authenticate(user=tenant)

    payload = {
        "tenancy_id": tenancy.id,
        "role": Review.ROLE_LANDLORD_TO_TENANT,  # wrong on purpose
        "overall_rating": 4,
        "notes": "Trying wrong role",
    }

    res = client.post(_reviews_create_url(), data=payload, format="json")
    assert res.status_code in (200, 201), getattr(res, "data", None)

    created = Review.objects.get(tenancy=tenancy, reviewer=tenant)
    assert created.role == Review.ROLE_TENANT_TO_LANDLORD
    assert created.reviewee_id == landlord.id
    assert created.reviewer_id == tenant.id
    assert int(created.overall_rating) == 4


def test_landlord_payload_cannot_force_tenant_role(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rp_landlord2")
    tenant = user_factory(username="rp_tenant2")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    client.force_authenticate(user=landlord)

    payload = {
        "tenancy_id": tenancy.id,
        "role": Review.ROLE_TENANT_TO_LANDLORD,  # wrong on purpose
        "overall_rating": 4,
        "notes": "Trying wrong role",
    }

    res = client.post(_reviews_create_url(), data=payload, format="json")
    assert res.status_code in (200, 201), getattr(res, "data", None)

    created = Review.objects.get(tenancy=tenancy, reviewer=landlord)
    assert created.role == Review.ROLE_LANDLORD_TO_TENANT
    assert created.reviewee_id == tenant.id
    assert created.reviewer_id == landlord.id
    assert int(created.overall_rating) == 4


def test_random_user_cannot_submit_review_for_tenancy(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rp_landlord3")
    tenant = user_factory(username="rp_tenant3")
    stranger = user_factory(username="rp_stranger3")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    client.force_authenticate(user=stranger)

    payload = {
        "tenancy_id": tenancy.id,
        "role": Review.ROLE_TENANT_TO_LANDLORD,
        "overall_rating": 1,
        "notes": "Not a party to this tenancy",
    }

    res = client.post(_reviews_create_url(), data=payload, format="json")
    assert res.status_code in (400, 403, 404), getattr(res, "data", None)

    assert not Review.objects.filter(tenancy=tenancy).exists()