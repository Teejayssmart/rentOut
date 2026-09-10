from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from propertylist_app.api.views.rooms import RoomDetailAV
from propertylist_app.models import Room, RoomCategorie, UserProfile


@pytest.mark.django_db
def test_room_detail_fetches_category_owner_profile_without_extra_queries(
    django_user_model,
    django_assert_num_queries,
):
    owner = django_user_model.objects.create_user(
        username="room_detail_perf_owner",
        email="room_detail_perf_owner@example.com",
        password="testpass123",
    )
    profile, _ = UserProfile.objects.get_or_create(user=owner)
    profile.role = "landlord"
    profile.save(update_fields=["role"])

    category = RoomCategorie.objects.create(
        name="Room detail performance",
        active=True,
    )

    room = Room.objects.create(
        title="Room detail performance room",
        description="Room detail related query performance regression fixture.",
        location="SO14 0AA",
        price_per_month=800,
        security_deposit=800,
        property_owner=owner,
        category=category,
        status="active",
        is_available=True,
        paid_until=timezone.localdate() + timedelta(days=30),
    )

    factory = APIRequestFactory()
    django_request = factory.get(f"/api/v1/rooms/{room.id}/")

    view = RoomDetailAV()
    request = view.initialize_request(django_request)

    with django_assert_num_queries(1):
        fetched_room = view._get_room(request, room.id)
        related_values = (
            fetched_room.category.name,
            fetched_room.property_owner.username,
            fetched_room.property_owner.profile.role,
        )

    assert related_values == (
        "Room detail performance",
        "room_detail_perf_owner",
        "landlord",
    )
