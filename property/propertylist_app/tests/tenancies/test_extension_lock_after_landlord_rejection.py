from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import (
    Message,
    MessageThread,
    Tenancy,
    TenancyExtension,
)


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("actor_role", ["tenant", "landlord"])
def test_landlord_rejection_of_tenant_extension_blocks_further_updates_for_both_parties(
    user_factory,
    room_factory,
    actor_role,
):
    landlord = user_factory(username=f"extension_lock_landlord_{actor_role}")
    tenant = user_factory(username=f"extension_lock_tenant_{actor_role}")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=3,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
        still_living_check_at=now - timedelta(minutes=1),
        review_open_at=now + timedelta(minutes=9),
    )

    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=tenant,
        proposed_start_date=date.today() + timedelta(days=1),
        proposed_duration_months=6,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    thread = MessageThread.objects.create()
    thread.participants.set([landlord, tenant])
    ending_message = Message.objects.create(
        thread=thread,
        sender=landlord,
        body="Your tenancy is ending soon.",
        metadata={
            "system_event": True,
            "event_type": "still_living_check",
            "tenancy_id": tenancy.id,
            "room_id": room.id,
            "available_actions": ["update_tenancy"],
        },
    )

    client = APIClient()
    client.force_authenticate(user=landlord)
    reject_response = client.patch(
        f"/api/v1/tenancies/{tenancy.id}/extensions/{extension.id}/respond/",
        data={"action": "reject"},
        format="json",
    )

    assert reject_response.status_code == 200, reject_response.data
    extension.refresh_from_db()
    assert extension.status == TenancyExtension.STATUS_REJECTED

    actor = tenant if actor_role == "tenant" else landlord
    client.force_authenticate(user=actor)

    messages_response = client.get(
        reverse(
            "v1:thread-messages",
            kwargs={"thread_id": thread.id},
        )
    )
    assert messages_response.status_code == 200, messages_response.data
    items = messages_response.data.get(
        "data",
        messages_response.data.get("results", []),
    )
    item = next(
        item
        for item in items
        if item["id"] == ending_message.id
    )
    assert item["available_actions"] == []

    retry_response = client.post(
        f"/api/v1/tenancies/{tenancy.id}/extensions/",
        data={
            "proposed_start_date": str(date.today() + timedelta(days=2)),
            "proposed_duration_months": 6,
        },
        format="json",
    )

    assert retry_response.status_code == 400, retry_response.data
    assert TenancyExtension.objects.filter(tenancy=tenancy).count() == 1
