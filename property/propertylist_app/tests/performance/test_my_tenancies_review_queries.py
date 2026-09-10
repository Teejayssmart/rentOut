from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from propertylist_app.api.serializers import TenancyDetailSerializer
from propertylist_app.api.views.tenancies import MyTenanciesView
from propertylist_app.models import Tenancy, UserProfile


@pytest.mark.django_db
def test_my_tenancies_does_not_query_review_eligibility_per_tenancy(
    django_user_model,
    room_factory,
    django_assert_num_queries,
):
    tenant = django_user_model.objects.create_user(
        username="tenancy_perf_tenant",
        email="tenancy_perf_tenant@example.com",
        password="testpass123",
    )
    landlord = django_user_model.objects.create_user(
        username="tenancy_perf_landlord",
        email="tenancy_perf_landlord@example.com",
        password="testpass123",
    )

    tenant_profile, _ = UserProfile.objects.get_or_create(user=tenant)
    tenant_profile.role = "seeker"
    tenant_profile.save(update_fields=["role"])

    now = timezone.now()

    for index in range(3):
        room = room_factory(
            property_owner=landlord,
            title=f"Tenancy performance room {index}",
        )
        Tenancy.objects.create(
            room=room,
            landlord=landlord,
            tenant=tenant,
            proposed_by=landlord,
            move_in_date=date.today() - timedelta(days=60),
            duration_months=1,
            status=Tenancy.STATUS_ENDED,
            landlord_confirmed_at=now - timedelta(days=60),
            tenant_confirmed_at=now - timedelta(days=60),
            review_open_at=now - timedelta(days=1),
            review_deadline_at=now + timedelta(days=7),
        )

    factory = APIRequestFactory()
    django_request = factory.get("/api/v1/tenancies/mine/")
    force_authenticate(django_request, user=tenant)

    view = MyTenanciesView()
    request = view.initialize_request(django_request)
    view.request = request
    view.args = ()
    view.kwargs = {}

    with django_assert_num_queries(2):
        tenancies = list(view.get_queryset())
        TenancyDetailSerializer(
            tenancies,
            many=True,
            context={"request": request},
        ).data
