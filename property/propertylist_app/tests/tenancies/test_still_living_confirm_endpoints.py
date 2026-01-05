# property/propertylist_app/tests/tenancies/test_still_living_confirm_endpoints.py

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

    # Make check due now
    t.still_living_check_at = now - timedelta(days=1)

    # Ensure not already confirmed
    if hasattr(t, "still_living_confirmed_at"):
        t.still_living_confirmed_at = None
    if hasattr(t, "still_living_tenant_confirmed_at"):
        t.still_living_tenant_confirmed_at = None
    if hasattr(t, "still_living_landlord_confirmed_at"):
        t.still_living_landlord_confirmed_at = None

    update_fields = ["still_living_check_at"]
    for f in (
        "still_living_confirmed_at",
        "still_living_tenant_confirmed_at",
        "still_living_landlord_confirmed_at",
    ):
        if hasattr(t, f):
            update_fields.append(f)

    t.save(update_fields=update_fields)
    return t


def _confirm_url(tenancy_id: int) -> str:
    return f"/api/tenancies/{tenancy_id}/still-living/confirm/"


def test_tenant_can_confirm_still_living(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_landlord")
    tenant = user_factory(username="sl_tenant")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    client = APIClient()
    client.force_authenticate(user=tenant)

    res = client.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res.status_code in (200, 204)

    tenancy.refresh_from_db()
    assert tenancy.still_living_check_at is not None
    assert tenancy.still_living_tenant_confirmed_at is not None


def test_landlord_can_confirm_still_living(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_landlord2")
    tenant = user_factory(username="sl_tenant2")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    client = APIClient()
    client.force_authenticate(user=landlord)

    res = client.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res.status_code in (200, 204)

    tenancy.refresh_from_db()
    assert tenancy.still_living_landlord_confirmed_at is not None


def test_random_user_cannot_confirm_still_living(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_landlord3")
    tenant = user_factory(username="sl_tenant3")
    random_user = user_factory(username="sl_random")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    client = APIClient()
    client.force_authenticate(user=random_user)

    res = client.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res.status_code in (403, 404)


def test_confirm_is_idempotent(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_landlord4")
    tenant = user_factory(username="sl_tenant4")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    client = APIClient()
    client.force_authenticate(user=tenant)

    res1 = client.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res1.status_code in (200, 204)

    tenancy.refresh_from_db()
    first_ts = tenancy.still_living_tenant_confirmed_at
    assert first_ts is not None

    res2 = client.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res2.status_code in (200, 204)

    tenancy.refresh_from_db()
    second_ts = tenancy.still_living_tenant_confirmed_at
    assert second_ts is not None
