from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Review, Tenancy


pytestmark = pytest.mark.django_db


def _make_ended_tenancy(room, landlord, tenant):
    now = timezone.now()
    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=30),
        duration_months=1,
        status=Tenancy.STATUS_ENDED,
        landlord_confirmed_at=now - timedelta(days=30),
        tenant_confirmed_at=now - timedelta(days=30),
        review_open_at=now - timedelta(minutes=1),
        review_deadline_at=now + timedelta(minutes=9),
    )


def _tenancy_payload(response, tenancy_id):
    payload = response.json()
    data = payload["data"]
    items = data["results"] if isinstance(data, dict) else data
    return next(
        item for item in items if item["id"] == tenancy_id
    )


def test_my_tenancies_exposes_authoritative_review_button_state(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="review_button_landlord")
    tenant = user_factory(username="review_button_tenant")
    room = room_factory(property_owner=landlord)
    tenancy = _make_ended_tenancy(room, landlord, tenant)

    client = APIClient()
    client.force_authenticate(user=tenant)

    response = client.get("/api/v1/tenancies/mine/")

    assert response.status_code == 200
    tenancy_payload = _tenancy_payload(response, tenancy.id)
    assert tenancy_payload["can_leave_review"] is True
    assert tenancy_payload["review_button_reason"] == "Review is available."

    Review.objects.create(
        tenancy=tenancy,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        overall_rating=5,
        notes="Good landlord.",
    )

    response = client.get("/api/v1/tenancies/mine/")

    assert response.status_code == 200
    tenancy_payload = _tenancy_payload(response, tenancy.id)
    assert tenancy_payload["can_leave_review"] is False
    assert (
        tenancy_payload["review_button_reason"]
        == "You have already submitted a review for this tenancy."
    )
