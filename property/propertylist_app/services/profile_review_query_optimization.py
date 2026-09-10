from django.db.models import Avg, Count, Q
from django.utils import timezone


def install_profile_review_query_optimization():
    """Reduce repeated review aggregate queries on the profile page."""
    from propertylist_app.api.serializers import ProfilePageSerializer, ReviewSerializer
    from propertylist_app.api.views.common import ok_response
    from propertylist_app.api.views.profile import MyProfilePageView
    from propertylist_app.models import Review, UserProfile
    from rest_framework import status

    if getattr(MyProfilePageView, "_review_query_optimization_installed", False):
        return

    def get(self, request):
        user = request.user
        profile, _ = UserProfile.objects.get_or_create(user=user)
        now = timezone.now()

        qs = Review.objects.filter(
            reviewee_id=user.id,
            reveal_at__isnull=False,
            reveal_at__lte=now,
            active=True,
        )

        stats = qs.aggregate(
            landlord_count=Count(
                "id", filter=Q(role=Review.ROLE_TENANT_TO_LANDLORD)
            ),
            tenant_count=Count(
                "id", filter=Q(role=Review.ROLE_LANDLORD_TO_TENANT)
            ),
            landlord_avg=Avg(
                "overall_rating", filter=Q(role=Review.ROLE_TENANT_TO_LANDLORD)
            ),
            tenant_avg=Avg(
                "overall_rating", filter=Q(role=Review.ROLE_LANDLORD_TO_TENANT)
            ),
        )

        landlord_count = stats["landlord_count"]
        tenant_count = stats["tenant_count"]
        landlord_avg = stats["landlord_avg"]
        tenant_avg = stats["tenant_avg"]

        if profile.role == "landlord":
            current_role = Review.ROLE_TENANT_TO_LANDLORD
            total = landlord_count
            overall = landlord_avg
        else:
            current_role = Review.ROLE_LANDLORD_TO_TENANT
            total = tenant_count
            overall = tenant_avg

        preview = ReviewSerializer(
            qs.filter(role=current_role).order_by("-submitted_at")[:2],
            many=True,
            context={"request": request},
        ).data

        age = None
        if profile.date_of_birth:
            today = now.date()
            dob = profile.date_of_birth
            age = today.year - dob.year - (
                (today.month, today.day) < (dob.month, dob.day)
            )

        location = (profile.address_manual or "").strip()
        if not location:
            location = (profile.postcode or "").strip()

        payload = {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "date_joined": user.date_joined,
            "avatar": (profile.avatar.url if profile.avatar else None),
            "role": profile.role,
            "gender": profile.get_gender_display() if profile.gender else "",
            "occupation": profile.occupation or "",
            "postcode": profile.postcode or "",
            "address_manual": profile.address_manual or "",
            "date_of_birth": profile.date_of_birth,
            "about_you": profile.about_you or "",
            "age": age,
            "location": location,
            "total_reviews": total,
            "overall_rating": overall,
            "landlord_reviews_count": landlord_count,
            "landlord_rating_average": landlord_avg,
            "tenant_reviews_count": tenant_count,
            "tenant_rating_average": tenant_avg,
            "reviews_preview": preview,
            "landlord_verified": bool(
                getattr(profile, "advertiser_verified", False)
            ),
        }

        serializer = ProfilePageSerializer(payload, context={"request": request})
        return ok_response(
            serializer.data,
            message="Profile page retrieved successfully.",
            status_code=status.HTTP_200_OK,
        )

    MyProfilePageView.get = get
    MyProfilePageView._review_query_optimization_installed = True
