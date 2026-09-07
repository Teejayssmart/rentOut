from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from propertylist_app.api.views import public as public_views
from propertylist_app.models import Room, RoomCategorie, UserProfile


class _ProfileTouchingHomeSerializer:
    """Minimal stand-in that exercises the owner-profile data RoomSerializer needs."""

    def __init__(self, payload, context=None):
        self.payload = payload

    @property
    def data(self):
        featured = list(self.payload["featured_rooms"])
        latest = list(self.payload["latest_rooms"])

        for room in [*featured, *latest]:
            profile = room.property_owner.profile
            _ = profile.role_detail
            _ = profile.advertiser_verified
            _ = profile.allow_search_indexing_default

        return {
            "featured_rooms": [],
            "latest_rooms": [],
            "popular_cities": self.payload["popular_cities"],
            "stats": self.payload["stats"],
            "app_links": self.payload["app_links"],
        }


@pytest.mark.django_db
def test_homepage_fetches_owner_profiles_without_per_room_queries(
    django_user_model,
    django_assert_num_queries,
    monkeypatch,
):
    category = RoomCategorie.objects.create(name="Homepage perf", active=True)

    for index in range(2):
        landlord = django_user_model.objects.create_user(
            username=f"homepage_perf_landlord_{index}",
            email=f"homepage_perf_landlord_{index}@example.com",
            password="testpass123",
        )
        profile, _ = UserProfile.objects.get_or_create(user=landlord)
        profile.role = "landlord"
        profile.role_detail = "live_out_landlord"
        profile.advertiser_verified = True
        profile.save(update_fields=["role", "role_detail", "advertiser_verified"])

        Room.objects.create(
            title=f"Homepage performance room {index}",
            description="A homepage performance regression room.",
            location="SO14 0AA",
            price_per_month=700 + index,
            security_deposit=700,
            property_owner=landlord,
            category=category,
            status="active",
            is_available=True,
            paid_until=timezone.localdate() + timedelta(days=30),
        )

    monkeypatch.setattr(
        public_views,
        "HomeSummarySerializer",
        _ProfileTouchingHomeSerializer,
    )

    request = APIRequestFactory().get("/api/v1/home/")

    # Expected fixed cost:
    # 1 featured query + 1 latest query + 1 city aggregation + 3 stats queries.
    # Accessing each room owner's profile must not add another query per room.
    with django_assert_num_queries(6):
        response = public_views.HomePageView.as_view()(request)

    assert response.status_code == 200
