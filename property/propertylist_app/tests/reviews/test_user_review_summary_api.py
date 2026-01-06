import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Review


def review_summary_url(user_id: int) -> str:
    return f"/api/users/{user_id}/review-summary/"


@pytest.mark.django_db
def test_review_summary_total_is_sum_of_landlord_and_tenant_counts():
    """
    Ensures total_reviews_count is NOT hard-coded.
    It must always equal landlord_count + tenant_count for the same reviewee.
    Also checks overall_rating_average is weighted correctly.
    """
    client = APIClient()

    # Use your existing test helper if available in your project.
    # If your project uses make_user() from a shared tests helper, replace these
    # two lines with: reviewee = make_user(...), reviewer = make_user(...)
    from django.contrib.auth import get_user_model
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

    # 2 landlord reviews (tenant_to_landlord) with rating 5 each
    Review.objects.create(
        reviewer=reviewer,
        reviewee=reviewee,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["friendly", "good_communication"],  # pos=2 => score 5  # pos=2 => score 5
        reveal_at=now,
        active=True,
        notes="Great landlord",
    )

    Review.objects.create(
      reviewer=reviewer,
      reviewee=reviewee,
      role=Review.ROLE_TENANT_TO_LANDLORD,
      review_flags=["paid_on_time", "followed_rules"],  # pos=2 => score 5,  # pos=2 => score 5
      reveal_at=now,
      active=True,
      notes="Very responsive",
  )


    # 1 tenant review (landlord_to_tenant) with rating 3
    Review.objects.create(
        reviewer=reviewer,
        reviewee=reviewee,
        role=Review.ROLE_LANDLORD_TO_TENANT,
        review_flags=[],  # pos=0, neg=0 => score 3
        reveal_at=now,
        active=True,
        notes="Okay tenant",
    )


    res = client.get(review_summary_url(reviewee.id))
    print("SUMMARY RESPONSE:", res.data)
    assert res.status_code == 200


    landlord_count = res.data["landlord_count"]
    tenant_count = res.data["tenant_count"]
    total = res.data["total_reviews_count"]

    assert landlord_count == 2
    assert tenant_count == 1
    assert total == landlord_count + tenant_count  # critical check

    # weighted overall average: (5*2 + 3*1) / 3 = 13/3 = 4.333333...
    expected = (5 * 2 + 3 * 1) / 3
    assert res.data["overall_rating_average"] == pytest.approx(expected, rel=1e-6)
