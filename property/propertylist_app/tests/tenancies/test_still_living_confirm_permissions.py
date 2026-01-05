# property/propertylist_app/tests/tenancies/test_still_living_confirm_permissions.py

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
        still_living_check_at=timezone.now() - timedelta(days=1),
        still_living_confirmed_at=None,
        still_living_landlord_confirmed_at=None,
        still_living_tenant_confirmed_at=None,
    )


def _confirm_url(tenancy_id: int) -> str:
    return f"/api/tenancies/{tenancy_id}/still-living/confirm/"


def test_tenant_can_confirm(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_perm_landlord1")
    tenant = user_factory(username="sl_perm_tenant1")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    c = APIClient()
    c.force_authenticate(user=tenant)

    res = c.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res.status_code == 200

    tenancy.refresh_from_db()
    assert tenancy.still_living_tenant_confirmed_at is not None


def test_landlord_can_confirm(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_perm_landlord2")
    tenant = user_factory(username="sl_perm_tenant2")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    c = APIClient()
    c.force_authenticate(user=landlord)

    res = c.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res.status_code == 200

    tenancy.refresh_from_db()
    assert tenancy.still_living_landlord_confirmed_at is not None


def test_random_user_cannot_confirm(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_perm_landlord3")
    tenant = user_factory(username="sl_perm_tenant3")
    random_user = user_factory(username="sl_perm_random3")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    c = APIClient()
    c.force_authenticate(user=random_user)

    res = c.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res.status_code in (403, 404)


def test_confirm_is_idempotent(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_perm_landlord4")
    tenant = user_factory(username="sl_perm_tenant4")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    c = APIClient()
    c.force_authenticate(user=tenant)

    res1 = c.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res1.status_code == 200

    tenancy.refresh_from_db()
    first_ts = tenancy.still_living_tenant_confirmed_at

    res2 = c.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res2.status_code == 200

    tenancy.refresh_from_db()
    assert tenancy.still_living_tenant_confirmed_at == first_ts


def test_confirm_unknown_tenancy_returns_404(user_factory):
    user = user_factory(username="sl_perm_user5")

    c = APIClient()
    c.force_authenticate(user=user)

    res = c.patch(_confirm_url(999999), data={}, format="json")
    assert res.status_code == 404
