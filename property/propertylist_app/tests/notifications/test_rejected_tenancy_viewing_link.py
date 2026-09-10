from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import (
    Booking,
    Notification,
    Room,
    RoomCategorie,
    Tenancy,
    UserProfile,
)
from propertylist_app.tasks import task_send_tenancy_notification


User = get_user_model()


@pytest.mark.django_db
def test_rejected_unverified_tenant_bell_links_to_completed_viewing():
    landlord = User.objects.create_user(
        username="rejected_link_landlord",
        password="pass",
    )
    tenant = User.objects.create_user(
        username="rejected_link_tenant",
        password="pass",
    )
    UserProfile.objects.create(
        user=tenant,
        role="seeker",
    )

    category = RoomCategorie.objects.create(
        name="Rejected link test",
        active=True,
    )
    room = Room.objects.create(
        title="Rejected link room",
        description="x",
        price_per_month=650,
        location="SW1A 1AA",
        category=category,
        property_owner=landlord,
    )
    viewing = Booking.objects.create(
        room=room,
        user=tenant,
        start=timezone.now() - timedelta(minutes=40),
        end=timezone.now() - timedelta(minutes=10),
        status=Booking.STATUS_ACTIVE,
    )
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=timezone.localdate(),
        duration_months=6,
        status=Tenancy.STATUS_CANCELLED,
    )

    task_send_tenancy_notification(
        tenancy.id,
        "rejected_unverified",
    )

    notification = Notification.objects.get(
        user=tenant,
        type="tenancy_rejected_unverified",
    )

    # Keep the stored lifecycle target unchanged so notification retries
    # remain idempotent. Only the bell CTA is redirected to the viewing.
    assert notification.target_type == "tenancy"
    assert notification.target_id == tenancy.id
    assert notification.thread_id is not None

    client = APIClient()
    client.force_authenticate(user=tenant)
    response = client.get("/api/v1/notifications/")

    assert response.status_code == 200
    payload = response.json()
    items = payload["data"]
    bell_item = next(
        item
        for item in items
        if item["id"] == notification.id
    )

    assert bell_item["cta_url"] == f"/viewings/{viewing.id}"
