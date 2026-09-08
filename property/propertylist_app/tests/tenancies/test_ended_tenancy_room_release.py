from datetime import date, timedelta

import pytest
from django.utils import timezone

from propertylist_app.models import Tenancy
from propertylist_app.tasks import task_tenancy_prompts_sweep


pytestmark = pytest.mark.django_db


def test_review_window_transition_releases_ended_tenancy_room_for_reletting(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="ended_room_release_landlord")
    tenant = user_factory(username="ended_room_release_tenant")
    room = room_factory(property_owner=landlord)

    # The room is unavailable while the tenancy is still running.
    room.is_available = False
    room.save(update_fields=["is_available"])

    now = timezone.now()
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today(),
        duration_months=12,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=now - timedelta(minutes=30),
        tenant_confirmed_at=now - timedelta(minutes=30),
        review_open_at=now - timedelta(minutes=1),
        review_deadline_at=now + timedelta(minutes=9),
        still_living_confirmed_at=None,
    )

    task_tenancy_prompts_sweep()

    tenancy.refresh_from_db()
    room.refresh_from_db()

    assert tenancy.status == Tenancy.STATUS_ENDED
    assert room.is_available is True
