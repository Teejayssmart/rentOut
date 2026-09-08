from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.api.serializers import RoomSerializer
from propertylist_app.models import Tenancy
from propertylist_app.tasks import task_refresh_tenancy_status_and_review_windows


pytestmark = pytest.mark.django_db


def _auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_publish_stamps_relisted_at_after_ended_tenancy_even_when_room_is_already_active(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="relist_landlord")
    tenant = user_factory(username="relist_tenant")
    room = room_factory(property_owner=landlord)

    room.status = "active"
    room.is_available = True
    room.paid_until = date.today() + timedelta(days=7)
    room.relisted_at = None
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "relisted_at",
            "updated_at",
        ]
    )

    Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=2,
        status=Tenancy.STATUS_ENDED,
        landlord_confirmed_at=timezone.now() - timedelta(days=90),
        tenant_confirmed_at=timezone.now() - timedelta(days=90),
    )

    before = timezone.now()
    response = _auth_client(landlord).post(
        reverse("api:room-publish", args=[room.id]),
        {},
        format="json",
    )

    assert response.status_code == 200, response.data

    room.refresh_from_db()
    assert room.status == "active"
    assert room.is_available is True
    assert room.relisted_at is not None
    assert room.relisted_at >= before

    mine_response = _auth_client(landlord).get(reverse("api:my-listings"))
    assert mine_response.status_code == 200, mine_response.data
    mine_room = next(item for item in mine_response.data if item["id"] == room.id)
    assert mine_room["relisted_at"] is not None

    assert RoomSerializer().fields["relisted_at"].read_only is True


def test_real_tenancy_end_clears_previous_relist_stamp(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="relist_reset_landlord")
    tenant = user_factory(username="relist_reset_tenant")
    room = room_factory(property_owner=landlord)

    room.is_available = False
    room.relisted_at = timezone.now() - timedelta(days=1)
    room.save(
        update_fields=[
            "is_available",
            "relisted_at",
            "updated_at",
        ]
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=120),
        duration_months=3,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=timezone.now() - timedelta(days=120),
        tenant_confirmed_at=timezone.now() - timedelta(days=120),
    )

    task_refresh_tenancy_status_and_review_windows()

    tenancy.refresh_from_db()
    room.refresh_from_db()

    assert tenancy.status == Tenancy.STATUS_ENDED
    assert room.is_available is True
    assert room.relisted_at is None
