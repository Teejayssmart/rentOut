import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Review, Tenancy

pytestmark = pytest.mark.django_db


def test_tenant_to_landlord_flags_auto_calculate_overall_rating(user_factory, room_factory):
    """
    Tenant -> Landlord rating calculation must work from checklist flags.

    Expected formula (int):
    score = 3 + (positives - negatives), clamped to 1..5
    """
    landlord = user_factory(username="t2l_landlord", role="landlord")
    tenant = user_factory(username="t2l_tenant", role="seeker")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    move_in = timezone.localdate() - timedelta(days=40)  # any date in the past is fine

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        status=getattr(Tenancy, "STATUS_ENDED", "ended"),
        move_in_date=move_in,  #  required by DB
        duration_months=6,
        review_open_at=now - timedelta(days=1),
        review_deadline_at=now + timedelta(days=10),
    )


    client = APIClient()
    client.force_authenticate(user=tenant)

    # Tenant -> Landlord flags:
    # positives: responsive, maintenance_good, accurate_listing (3)
    # negatives: unresponsive (1)
    # score = 3 + (3-1) = 5
    flags = ["responsive", "maintenance_good", "accurate_listing", "unresponsive"]

    res = client.post(
        f"/api/v1/tenancies/{tenancy.id}/reviews/",
        data={"review_flags": flags},
        format="json",
    )
    assert res.status_code == 201, res.data

    review = Review.objects.get(id=res.data["id"])
    assert review.role == Review.ROLE_TENANT_TO_LANDLORD
    assert review.overall_rating == 5
