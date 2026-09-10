import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIRequestFactory, force_authenticate

from propertylist_app.api.views.profile import MyProfilePageView
from propertylist_app.models import UserProfile


@pytest.mark.django_db
def test_my_profile_page_aggregates_review_stats_without_repeated_queries(
    django_user_model,
):
    user = django_user_model.objects.create_user(
        username="profile_perf_user",
        email="profile_perf_user@example.com",
        password="testpass123",
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = "landlord"
    profile.save(update_fields=["role"])

    factory = APIRequestFactory()
    request = factory.get("/api/v1/users/me/profile-page/")
    force_authenticate(request, user=user)

    with CaptureQueriesContext(connection) as captured:
        response = MyProfilePageView.as_view()(request)

    assert response.status_code == 200

    review_queries = [
        query["sql"]
        for query in captured.captured_queries
        if "propertylist_app_review" in query["sql"].lower()
    ]

    assert len(review_queries) == 2, "\n\n".join(review_queries)
