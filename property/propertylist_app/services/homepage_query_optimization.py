from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status

from propertylist_app.api.views.common import ok_response
from propertylist_app.models import Room, UserProfile


def install_homepage_owner_profile_query_optimization():
    """Ensure HomePageView fetches landlord profiles with each room query."""
    from propertylist_app.api.views import public as public_views

    if getattr(public_views.HomePageView, "_owner_profile_query_optimized", False):
        return

    def get(self, request):
        today = timezone.now().date()

        base_rooms = (
            Room.objects.alive()
            .filter(status="active")
            .filter(Q(paid_until__isnull=True) | Q(paid_until__gte=today))
            .select_related("category", "property_owner", "property_owner__profile")
        )

        featured_rooms_qs = base_rooms.order_by(
            "-avg_rating",
            "-number_rating",
            "-created_at",
        )[:6]
        latest_rooms_qs = base_rooms.order_by("-created_at")[:6]

        city_rows = (
            base_rooms
            .exclude(location__isnull=True)
            .exclude(location__exact="")
            .values("location")
            .annotate(room_count=Count("id"))
            .order_by("-room_count", "location")[:12]
        )
        popular_cities = [
            {"name": row["location"], "room_count": row["room_count"]}
            for row in city_rows
        ]

        stats = {
            "total_active_rooms": base_rooms.count(),
            "total_landlords": UserProfile.objects.filter(role="landlord").count(),
            "total_seekers": UserProfile.objects.filter(role="seeker").count(),
        }

        app_links = {
            "ios": getattr(settings, "MOBILE_APP_IOS_URL", ""),
            "android": getattr(settings, "MOBILE_APP_ANDROID_URL", ""),
        }

        payload = {
            "featured_rooms": featured_rooms_qs,
            "latest_rooms": latest_rooms_qs,
            "popular_cities": popular_cities,
            "stats": stats,
            "app_links": app_links,
        }

        serializer = public_views.HomeSummarySerializer(
            payload,
            context={"request": request},
        )
        return ok_response(serializer.data, status_code=status.HTTP_200_OK)

    public_views.HomePageView.get = get
    public_views.HomePageView._owner_profile_query_optimized = True
