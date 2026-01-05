# property/propertylist_app/tests/tenancies/test_still_living_sweep_stops_after_confirm.py

from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.tasks import task_tenancy_prompts_sweep


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
    )


def _confirm_url(tenancy_id: int) -> str:
    return f"/api/tenancies/{tenancy_id}/still-living/confirm/"


def test_sweep_notifies_only_unconfirmed_side_then_stops_when_both_confirm(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Notification = _get_model("propertylist_app", "Notification")

    landlord = user_factory(username="sl_stop_landlord1")
    tenant = user_factory(username="sl_stop_tenant1")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)
    tenancy.still_living_check_at = timezone.now() - timedelta(days=1)
    tenancy.still_living_confirmed_at = None
    tenancy.still_living_landlord_confirmed_at = None
    tenancy.still_living_tenant_confirmed_at = None
    tenancy.save(
        update_fields=[
            "still_living_check_at",
            "still_living_confirmed_at",
            "still_living_landlord_confirmed_at",
            "still_living_tenant_confirmed_at",
        ]
    )

    # 1) first sweep -> creates 2 notifications (both unconfirmed)
    before = Notification.objects.filter(type="tenancy_still_living_check").count()
    task_tenancy_prompts_sweep()
    mid = Notification.objects.filter(type="tenancy_still_living_check").count()
    assert mid == before + 2

    # 2) tenant confirms (PATCH, not POST)
    client = APIClient()
    client.force_authenticate(user=tenant)
    res = client.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res.status_code == 200

    # 3) next sweep -> should only notify LANDLORD (tenant already confirmed)
    task_tenancy_prompts_sweep()
    after_tenant_confirm = Notification.objects.filter(type="tenancy_still_living_check").count()
    assert after_tenant_confirm == mid + 1

    # 4) landlord confirms
    client = APIClient()
    client.force_authenticate(user=landlord)
    res = client.patch(_confirm_url(tenancy.id), data={}, format="json")
    assert res.status_code == 200

    # 5) next sweep -> should add NOTHING (both confirmed)
    task_tenancy_prompts_sweep()
    final_count = Notification.objects.filter(type="tenancy_still_living_check").count()
    assert final_count == after_tenant_confirm
