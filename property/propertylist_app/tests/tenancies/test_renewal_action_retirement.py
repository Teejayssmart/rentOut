from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from propertylist_app.tasks import task_tenancy_prompts_sweep


pytestmark = pytest.mark.django_db


def _model(name):
    return apps.get_model("propertylist_app", name)


def _make_active_tenancy(room, landlord, tenant):
    Tenancy = _model("Tenancy")
    now = timezone.now()

    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=30),
        duration_months=1,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=now - timedelta(days=30),
        tenant_confirmed_at=now - timedelta(days=30),
    )


def _proposal_message(extension):
    Message = _model("Message")
    return Message.objects.get(
        metadata__extension_id=extension.id,
        metadata__event_type="tenancy_extension_proposed",
        metadata__system_event=True,
    )


@pytest.mark.parametrize("response_status", ["accepted", "rejected"])
def test_renewal_response_retires_accept_and_reject_actions(
    user_factory,
    room_factory,
    response_status,
):
    TenancyExtension = _model("TenancyExtension")

    landlord = user_factory(username=f"retire_{response_status}_landlord")
    tenant = user_factory(username=f"retire_{response_status}_tenant")
    room = room_factory(property_owner=landlord)
    tenancy = _make_active_tenancy(room, landlord, tenant)

    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=date.today() + timedelta(days=1),
        proposed_duration_months=1,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    proposal_message = _proposal_message(extension)
    assert proposal_message.metadata["available_actions"] == [
        "accept",
        "reject",
    ]

    extension.status = response_status
    extension.responded_at = timezone.now()
    extension.save(update_fields=["status", "responded_at"])

    proposal_message.refresh_from_db()
    assert proposal_message.metadata["available_actions"] == []


def test_renewal_actions_retire_when_response_window_expires(
    user_factory,
    room_factory,
):
    TenancyExtension = _model("TenancyExtension")

    landlord = user_factory(username="retire_expired_landlord")
    tenant = user_factory(username="retire_expired_tenant")
    room = room_factory(property_owner=landlord)
    tenancy = _make_active_tenancy(room, landlord, tenant)

    tenancy.review_open_at = timezone.now() - timedelta(minutes=1)
    tenancy.review_deadline_at = timezone.now() + timedelta(minutes=9)
    tenancy.save(update_fields=["review_open_at", "review_deadline_at"])

    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=date.today() + timedelta(days=1),
        proposed_duration_months=1,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    proposal_message = _proposal_message(extension)
    assert proposal_message.metadata["available_actions"] == [
        "accept",
        "reject",
    ]

    task_tenancy_prompts_sweep()

    extension.refresh_from_db()
    proposal_message.refresh_from_db()

    assert extension.status == TenancyExtension.STATUS_CANCELED
    assert proposal_message.metadata["available_actions"] == []
