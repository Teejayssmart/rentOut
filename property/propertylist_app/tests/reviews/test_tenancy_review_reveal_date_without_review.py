from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Tenancy


pytestmark = pytest.mark.django_db


def test_tenancy_review_list_has_no_other_reveal_date_without_other_review(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="review_reveal_date_landlord")
    tenant = user_factory(username="review_reveal_date_tenant")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=date.today(),
        duration_months=12,
        landlord_confirmed_at=now,
        tenant_confirmed_at=now,
        status=Tenancy.STATUS_CONFIRMED,
        review_open_at=now,
        review_deadline_at=now + timedelta(days=30),
    )

    client = APIClient()
    client.force_authenticate(user=landlord)

    response = client.get(f"/api/v1/tenancies/{tenancy.id}/reviews/")

    assert response.status_code == 200, response.data
    assert response.data["other_review"] is None
    assert response.data["other_review_reveal_at"] is None
