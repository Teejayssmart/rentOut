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


def _auth(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _url():
    return "/api/v1/reviews/create/"


def test_xor_rejects_flags_plus_notes(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="xor_landlord_1")
    tenant = user_factory(username="xor_tenant_1")
    room = room_factory(property_owner=landlord)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = _auth(tenant)
    payload = {
        "tenancy_id": tenancy.id,
        "review_flags": ["responsive"],
        "notes": "Cannot send flags and free-text together.",
    }

    res = client.post(_url(), data=payload, format="json")
    assert res.status_code == 400, getattr(res, "data", None)


def test_xor_rejects_flags_plus_overall_rating(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="xor_landlord_2")
    tenant = user_factory(username="xor_tenant_2")
    room = room_factory(property_owner=landlord)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = _auth(tenant)
    payload = {
        "tenancy_id": tenancy.id,
        "review_flags": ["responsive"],
        "overall_rating": 5,
    }

    res = client.post(_url(), data=payload, format="json")
    assert res.status_code == 400, getattr(res, "data", None)


def test_xor_rejects_notes_only(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="xor_landlord_3")
    tenant = user_factory(username="xor_tenant_3")
    room = room_factory(property_owner=landlord)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = _auth(tenant)
    payload = {
        "tenancy_id": tenancy.id,
        "notes": "Text without rating is not allowed.",
    }

    res = client.post(_url(), data=payload, format="json")
    assert res.status_code == 400, getattr(res, "data", None)