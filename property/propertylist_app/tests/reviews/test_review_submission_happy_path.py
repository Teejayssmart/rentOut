# property/propertylist_app/tests/reviews/test_review_submission_happy_path.py

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

    # make review schedule "ready" (avoid: Tenancy review schedule is not ready yet.)
    if hasattr(t, "review_open_at"):
        t.review_open_at = now - timedelta(days=1)
    if hasattr(t, "review_deadline_at"):
        t.review_deadline_at = now + timedelta(days=7)
    t.save()

    return t


def _reviews_url(tenancy_id: int) -> str:
    # this is the endpoint your logs show: /api/tenancies/<id>/reviews/
    return f"/api/tenancies/{tenancy_id}/reviews/"


def test_tenant_can_submit_tenant_to_landlord_review_when_schedule_ready(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rh_landlord1")
    tenant = user_factory(username="rh_tenant1")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    client.force_authenticate(user=tenant)

    payload = {
        "tenancy_id": tenancy.id,
        "role": Review.ROLE_TENANT_TO_LANDLORD,
        "overall_rating": 5,
        "notes": "Great landlord",
    }

    res = client.post(_reviews_url(tenancy.id), data=payload, format="json")
    assert res.status_code in (200, 201), getattr(res, "data", None)

    r = Review.objects.filter(tenancy=tenancy, role=Review.ROLE_TENANT_TO_LANDLORD).latest("id")
    assert r.reviewer_id == tenant.id
    assert r.reviewee_id == landlord.id
    assert int(r.overall_rating) == 5


def test_landlord_can_submit_landlord_to_tenant_review_when_schedule_ready(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rh_landlord2")
    tenant = user_factory(username="rh_tenant2")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    client.force_authenticate(user=landlord)

    payload = {
        "tenancy_id": tenancy.id,
        "role": Review.ROLE_LANDLORD_TO_TENANT,
        "overall_rating": 4,
        "notes": "Good tenant",
    }

    res = client.post(_reviews_url(tenancy.id), data=payload, format="json")
    assert res.status_code in (200, 201), getattr(res, "data", None)

    r = Review.objects.filter(tenancy=tenancy, role=Review.ROLE_LANDLORD_TO_TENANT).latest("id")
    assert r.reviewer_id == landlord.id
    assert r.reviewee_id == tenant.id
    assert int(r.overall_rating) == 4
