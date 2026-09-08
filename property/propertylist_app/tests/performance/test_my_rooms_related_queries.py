from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from propertylist_app.api.views.rooms import MyRoomsView
from propertylist_app.models import Room, RoomCategorie, UserProfile


@pytest.mark.django_db
def test_my_rooms_fetches_owner_profile_without_per_room_queries(
    django_user_model,
    django_assert_num_queries,
):
    owner = django_user_model.objects.create_user(
        username="my_rooms_perf_owner",
        email="my_rooms_perf_owner@example.com",
        password="testpass123",
    )
    profile, _ = UserProfile.objects.get_or_create(user=owner)
    profile.role = "landlord"
    profile.save(update_fields=["role"])

    category = RoomCategorie.objects.create(
        name="My rooms performance",
        active=True,
    )

    for index in range(3):
        Room.objects.create(
            title=f"My rooms performance room {index}",
            description="My rooms related query performance regression fixture.",
            location="SO14 0AA",
            price_per_month=700 + index,
            security_deposit=700,
            property_owner=owner,
            category=category,
            status="active",
            is_available=True,
            paid_until=timezone.localdate() + timedelta(days=30),
        )

    factory = APIRequestFactory()
    django_request = factory.get("/api/v1/rooms/mine/")
    django_request.user = owner

    view = MyRoomsView()
    request = view.initialize_request(django_request)
    request.user = owner
    view.request = request

    # Fixed behaviour: each room's owner and owner profile must already be
    # present on the queryset rows, rather than triggering queries per room.
    with django_assert_num_queries(1):
        rooms = list(view.get_queryset())
        related_values = [
            (
                room.property_owner.username,
                room.property_owner.profile.role,
            )
            for room in rooms
        ]

    assert len(related_values) == 3
    assert {username for username, _ in related_values} == {
        "my_rooms_perf_owner"
    }
    assert {role for _, role in related_values} == {"landlord"}
