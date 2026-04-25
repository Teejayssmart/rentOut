import pytest
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, Tenancy, Review


def review_summary_url(user_id: int) -> str:
    return f"/api/v1/users/{user_id}/review-summary/"


def make_tenancy(*, room, landlord, tenant, proposed_by, now, offset_days):
    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=proposed_by,
        move_in_date=date.today() - timedelta(days=offset_days),
        duration_months=3,
        status=Tenancy.STATUS_ENDED,
        landlord_confirmed_at=now - timedelta(days=offset_days),
        tenant_confirmed_at=now - timedelta(days=offset_days),
        review_open_at=now - timedelta(days=1),
        review_deadline_at=now + timedelta(days=30),
    )


@pytest.mark.django_db
def test_review_summary_total_is_sum_of_landlord_and_tenant_counts():
    client = APIClient()
    User = get_user_model()

    reviewee = User.objects.create_user(
        username="reviewee_user",
        email="reviewee_user@example.com",
        password="pass12345",
    )
    reviewer = User.objects.create_user(
        username="reviewer_user",
        email="reviewer_user@example.com",
        password="pass12345",
    )

    now = timezone.now()

    cat = RoomCategorie.objects.create(name="Review Summary Category", active=True)

    room1 = Room.objects.create(
        title="Review Summary Room 1",
        description="Room for review summary test one",
        price_per_month=500,
        location="SO14",
        category=cat,
        property_owner=reviewee,
    )
    room2 = Room.objects.create(
        title="Review Summary Room 2",
        description="Room for review summary test two",
        price_per_month=600,
        location="SO15",
        category=cat,
        property_owner=reviewee,
    )
    room3 = Room.objects.create(
        title="Review Summary Room 3",
        description="Room for review summary test three",
        price_per_month=700,
        location="SO16",
        category=cat,
        property_owner=reviewee,
    )

    tenancy1 = make_tenancy(
        room=room1,
        landlord=reviewee,
        tenant=reviewer,
        proposed_by=reviewee,
        now=now,
        offset_days=90,
    )
    tenancy2 = make_tenancy(
        room=room2,
        landlord=reviewee,
        tenant=reviewer,
        proposed_by=reviewee,
        now=now,
        offset_days=120,
    )
    tenancy3 = make_tenancy(
        room=room3,
        landlord=reviewer,
        tenant=reviewee,
        proposed_by=reviewer,
        now=now,
        offset_days=150,
    )

    Review.objects.create(
        tenancy=tenancy1,
        reviewer=reviewer,
        reviewee=reviewee,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["responsive", "maintenance_good"],
        reveal_at=now,
        active=True,
        notes="Great landlord",
    )

    Review.objects.create(
        tenancy=tenancy2,
        reviewer=reviewer,
        reviewee=reviewee,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["accurate_listing", "respectful_fair"],
        reveal_at=now,
        active=True,
        notes="Very responsive",
    )

    Review.objects.create(
        tenancy=tenancy3,
        reviewer=reviewer,
        reviewee=reviewee,
        role=Review.ROLE_LANDLORD_TO_TENANT,
        overall_rating=3,
        review_flags=[],
        reveal_at=now,
        active=True,
        notes="Okay tenant",
    )

    res = client.get(review_summary_url(reviewee.id))
    assert res.status_code == 200, res.data

    landlord_count = res.data["landlord_count"]
    tenant_count = res.data["tenant_count"]
    total = res.data["total_reviews_count"]

    assert landlord_count == 2
    assert tenant_count == 1
    assert total == landlord_count + tenant_count

    expected = (5 * 2 + 3 * 1) / 3
    assert res.data["overall_rating_average"] == pytest.approx(expected, rel=1e-6)