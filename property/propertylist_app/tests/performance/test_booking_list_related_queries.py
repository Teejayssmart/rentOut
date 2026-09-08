from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from propertylist_app.api.serializers import BookingSerializer
from propertylist_app.api.views.bookings import BookingListCreateView
from propertylist_app.models import Booking, Room, RoomCategorie


@pytest.mark.django_db
def test_booking_list_fetches_room_and_user_without_per_booking_queries(
    django_user_model,
    django_assert_num_queries,
):
    seeker = django_user_model.objects.create_user(
        username="booking_perf_seeker",
        email="booking_perf_seeker@example.com",
        password="testpass123",
    )
    landlord = django_user_model.objects.create_user(
        username="booking_perf_landlord",
        email="booking_perf_landlord@example.com",
        password="testpass123",
    )
    category = RoomCategorie.objects.create(name="Booking performance", active=True)

    for index in range(3):
        room = Room.objects.create(
            title=f"Booking performance room {index}",
            description="Booking list performance regression fixture.",
            location="SO14 0AA",
            price_per_month=700 + index,
            security_deposit=700,
            property_owner=landlord,
            category=category,
            status="active",
            is_available=True,
            paid_until=timezone.localdate() + timedelta(days=30),
        )
        start = timezone.now() + timedelta(days=index + 1)
        Booking.objects.create(
            user=seeker,
            room=room,
            start=start,
            end=start + timedelta(hours=1),
            status="confirmed",
        )

    factory = APIRequestFactory()
    django_request = factory.get("/api/v1/bookings/")
    django_request.user = seeker

    view = BookingListCreateView()
    request = view.initialize_request(django_request)
    request.user = seeker
    view.request = request

    # Fixed behaviour: the bookings plus each booking's room and user should
    # be available from one joined query, not extra queries per booking.
    with django_assert_num_queries(1):
        data = BookingSerializer(
            view.get_queryset(),
            many=True,
            context={"request": request},
        ).data

    assert len(data) == 3
    assert {item["room_title"] for item in data} == {
        "Booking performance room 0",
        "Booking performance room 1",
        "Booking performance room 2",
    }
    assert {item["user_name"] for item in data} == {"booking_perf_seeker"}
