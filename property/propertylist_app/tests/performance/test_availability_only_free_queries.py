from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from propertylist_app.api.views.rooms import RoomAvailabilityPublicView
from propertylist_app.models import AvailabilitySlot, Room, RoomCategorie


@pytest.mark.django_db
def test_only_free_availability_does_not_query_bookings_per_slot(
    django_user_model,
    django_assert_num_queries,
):
    landlord = django_user_model.objects.create_user(
        username="availability_perf_landlord",
        email="availability_perf_landlord@example.com",
        password="testpass123",
    )
    category = RoomCategorie.objects.create(
        name="Availability performance",
        active=True,
    )
    room = Room.objects.create(
        title="Availability performance room",
        description="Availability query regression fixture.",
        location="SO14 0AA",
        price_per_month=700,
        security_deposit=700,
        property_owner=landlord,
        category=category,
        status="active",
        is_available=True,
        paid_until=timezone.localdate() + timedelta(days=30),
    )

    base_start = timezone.now() + timedelta(days=2)
    for index in range(4):
        start = base_start + timedelta(hours=index * 2)
        AvailabilitySlot.objects.create(
            room=room,
            start=start,
            end=start + timedelta(hours=1),
            max_bookings=1,
        )

    factory = APIRequestFactory()
    django_request = factory.get(
        f"/api/v1/rooms/{room.pk}/availability/?only_free=true"
    )

    view = RoomAvailabilityPublicView()
    request = view.initialize_request(django_request)
    view.request = request
    view.kwargs = {"pk": room.pk}

    # Fixed behaviour should use one query to resolve the room and one query
    # to fetch/filter all free slots, regardless of how many slots exist.
    with django_assert_num_queries(2):
        slots = list(view.get_queryset())

    assert len(slots) == 4
