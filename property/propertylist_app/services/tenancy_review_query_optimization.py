from django.db.models import Prefetch


def install_tenancy_review_query_optimization():
    """Keep tenancy-list review eligibility queries bounded."""
    from propertylist_app.api.serializers import TenancyDetailSerializer
    from propertylist_app.api.views.tenancies import MyTenanciesView
    from propertylist_app.models import Review

    if getattr(MyTenanciesView, "_review_query_optimization_installed", False):
        return

    original_get_queryset = MyTenanciesView.get_queryset
    original_get_review_eligibility = TenancyDetailSerializer._get_review_eligibility

    def get_queryset(self):
        queryset = original_get_queryset(self)
        return queryset.prefetch_related(
            Prefetch(
                "reviews",
                queryset=Review.objects.only("tenancy_id", "role"),
                to_attr="_prefetched_reviews",
            )
        )

    def get_review_eligibility(self, obj):
        prefetched_reviews = getattr(obj, "_prefetched_reviews", None)
        if prefetched_reviews is None:
            return original_get_review_eligibility(self, obj)

        request = self.context.get("request")
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return False, "You must be signed in to leave a review."

        if user.id == obj.tenant_id:
            review_role = Review.ROLE_TENANT_TO_LANDLORD
        elif user.id == obj.landlord_id:
            review_role = Review.ROLE_LANDLORD_TO_TENANT
        else:
            return False, "You are not part of this tenancy."

        if obj.status != "ended":
            return False, "A review can only be left after the tenancy has ended."

        if any(review.role == review_role for review in prefetched_reviews):
            return False, "You have already submitted a review for this tenancy."

        from django.utils import timezone

        now = timezone.now()

        if not obj.review_open_at:
            return False, "Review window is not open yet."

        if now < obj.review_open_at:
            return False, "Review will be available later."

        if obj.review_deadline_at and now > obj.review_deadline_at:
            return False, "Review window has closed."

        return True, "Review is available."

    MyTenanciesView.get_queryset = get_queryset
    TenancyDetailSerializer._get_review_eligibility = get_review_eligibility
    MyTenanciesView._review_query_optimization_installed = True
