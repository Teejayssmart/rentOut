# property/propertylist_app/tests/tenancies/test_still_living_confirm_permissions.py

from datetime import date, timedelta

import pytest
from django.apps import apps
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def _get_model(app_label, model_name):
    return apps.get_model(app_label, model_name)


def _make_tenancy(room, landlord, tenant, *, status):
    """
    Reason:
    Your Tenancy model fields can vary (some environments have extra still_living_* fields).
    This helper sets what exists, without assuming every field is present.
    """
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
    if hasattr(t, "still_living_check_at"):
        t.still_living_check_at = now - timedelta(days=1)

    # Ensure not already confirmed
    for f in (
        "still_living_confirmed_at",
        "still_living_landlord_confirmed_at",
        "still_living_tenant_confirmed_at",
    ):
        if hasattr(t, f):
            setattr(t, f, None)

    update_fields = []
    if hasattr(t, "still_living_check_at"):
        update_fields.append("still_living_check_at")
    for f in (
        "still_living_confirmed_at",
        "still_living_landlord_confirmed_at",
        "still_living_tenant_confirmed_at",
    ):
        if hasattr(t, f):
            update_fields.append(f)

    if update_fields:
        t.save(update_fields=update_fields)

    return t


def _confirm_url(tenancy_id: int) -> str:
    """
    Reason:
    Hardcoding '/api/...' causes 308 redirects in your project because you are migrating to '/api/v1/...'.
    Using reverse() hits the real v1 route directly (no redirect, no guessing).
    """
    return reverse("v1:tenancy-still-living-confirm", kwargs={"tenancy_id": tenancy_id})


def test_tenant_can_confirm(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_perm_landlord1")
    tenant = user_factory(username="sl_perm_tenant1")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    c = APIClient()
    c.force_authenticate(user=tenant)

    res = c.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res.status_code in (200, 204)

    tenancy.refresh_from_db()
    assert getattr(tenancy, "still_living_tenant_confirmed_at", None) is not None


def test_landlord_can_confirm(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_perm_landlord2")
    tenant = user_factory(username="sl_perm_tenant2")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    c = APIClient()
    c.force_authenticate(user=landlord)

    res = c.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res.status_code in (200, 204)

    tenancy.refresh_from_db()
    assert getattr(tenancy, "still_living_landlord_confirmed_at", None) is not None


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
    assert res1.status_code in (200, 204)

    tenancy.refresh_from_db()
    first_ts = getattr(tenancy, "still_living_tenant_confirmed_at", None)
    assert first_ts is not None

    res2 = c.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res2.status_code in (200, 204)

    tenancy.refresh_from_db()
    assert getattr(tenancy, "still_living_tenant_confirmed_at", None) == first_ts


def test_confirm_unknown_tenancy_returns_404(user_factory):
    user = user_factory(username="sl_perm_user5")

    c = APIClient()
    c.force_authenticate(user=user)

    res = c.patch(_confirm_url(999999), data={}, format="json")
    assert res.status_code == 404