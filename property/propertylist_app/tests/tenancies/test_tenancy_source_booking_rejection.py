from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Booking, Notification, Room, RoomCategorie, Tenancy
from propertylist_app.tasks import task_send_tenancy_notification


pytestmark = pytest.mark.django_db


def test_tenant_proposal_preserves_source_booking_for_rejection_notification():
    User = get_user_model()

    landlord = User.objects.create_user(
        username="source_booking_landlord",
        password="pass12345",
    )
    tenant = User.objects.create_user(
        username="source_booking_tenant",
        password="pass12345",
    )

    category = RoomCategorie.objects.create(
        name="Source booking category",
        active=True,
    )
    room = Room.objects.create(
        title="Source booking room",
        description="Room used to test tenancy booking provenance.",
        price_per_month="700.00",
        location="Southampton",
        category=category,
        property_owner=landlord,
        property_type="flat",
    )

    now = timezone.now()
    booking = Booking.objects.create(
        user=tenant,
        room=room,
        start=now - timedelta(days=1),
        end=now - timedelta(days=1) + timedelta(minutes=30),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )

    client = APIClient()
    client.force_authenticate(user=tenant)

    response = client.post(
        "/api/v1/tenancies/propose/",
        data={
            "room_id": room.id,
            "booking_id": booking.id,
            "counterparty_user_id": landlord.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )

    assert response.status_code == 201, response.data

    response_payload = response.data.get("data", response.data)
    tenancy = Tenancy.objects.get(id=response_payload["id"])

    assert tenancy.source_booking_id == booking.id

    task_send_tenancy_notification(
        tenancy.id,
        "rejected_unverified",
    )

    rejection = Notification.objects.get(
        user=tenant,
        type="tenancy_rejected_unverified",
    )

    assert f"(booking_id={booking.id})" in rejection.body
