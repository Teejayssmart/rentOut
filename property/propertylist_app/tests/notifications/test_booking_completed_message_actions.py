from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from propertylist_app.api.serializers import MessageSerializer
from propertylist_app.models import Booking, Message, Tenancy
from propertylist_app.services.message_threads import get_or_create_canonical_thread

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("submitted_by", ["landlord", "tenant"])
def test_completed_viewing_update_tenancy_action_disappears_for_both_parties_after_submission(
    user_factory,
    room_factory,
    submitted_by,
):
    landlord = user_factory(username=f"action_landlord_{submitted_by}")
    tenant = user_factory(username=f"action_tenant_{submitted_by}")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    booking = Booking.objects.create(
        user=tenant,
        room=room,
        start=now - timedelta(minutes=31),
        end=now - timedelta(minutes=1),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )

    thread = get_or_create_canonical_thread(
        landlord=landlord,
        seeker=tenant,
        room=room,
    )
    message = Message.objects.create(
        thread=thread,
        sender=landlord,
        body="Viewing completed",
        message_type=Message.TYPE_TEXT,
        metadata={
            "system_event": True,
            "event_type": "booking_completed",
            "booking_id": booking.id,
            "room_id": room.id,
        },
    )

    def actions_for(user):
        request = SimpleNamespace(user=user)
        return MessageSerializer(
            message,
            context={"request": request},
        ).data["available_actions"]

    assert actions_for(landlord) == ["update_tenancy"]
    assert actions_for(tenant) == ["update_tenancy"]

    proposer = landlord if submitted_by == "landlord" else tenant
    Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=proposer,
        move_in_date=timezone.localdate() + timedelta(days=7),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,
    )

    assert actions_for(landlord) == []
    assert actions_for(tenant) == []
