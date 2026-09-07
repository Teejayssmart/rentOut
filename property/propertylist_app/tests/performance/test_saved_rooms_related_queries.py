from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from propertylist_app.api.views.messaging import MySavedRoomsView
from propertylist_app.models import Room, RoomCategorie, SavedRoom, UserProfile


@pytest.mark.django_db
def test_saved_rooms_fetches_owner_profiles_without_per_room_queries(
    django_user_model,
    django_assert_num_queries,
):
    seeker = django_user_model.objects.create_user(
        username="saved_rooms_perf_seeker",
        email="saved_rooms_perf_seeker@example.com",
        password="testpass123",
    )
    seeker_profile, _ = UserProfile.objects.get_or_create(user=seeker)
    seeker_profile.role = "seeker"
    seeker_profile.save(update_fields=["role"])

    category = RoomCategorie.objects.create(name="Saved rooms perf", active=True)

    for index in range(3):
        landlord = django_user_model.objects.create_user(
            username=f"saved_rooms_perf_landlord_{index}",
            email=f"saved_rooms_perf_landlord_{index}@example.com",
            password="testpass123",
        )
        landlord_profile, _ = UserProfile.objects.get_or_create(user=landlord)
        landlord_profile.role = "landlord"
        landlord_profile.role_detail = "live_out_landlord"
        landlord_profile.advertiser_verified = True
        landlord_profile.save(
            update_fields=["role", "role_detail", "advertiser_verified"]
        )

        room = Room.objects.create(
            title=f"Saved rooms performance room {index}",
            description="A saved-room performance regression fixture.",
            location="SO14 0AA",
            price_per_month=700 + index,
            security_deposit=700,
            property_owner=landlord,
            category=category,
            status="active",
            is_available=True,
            paid_until=timezone.localdate() + timedelta(days=30),
        )
        SavedRoom.objects.create(user=seeker, room=room)

    factory = APIRequestFactory()
    django_request = factory.get("/api/v1/saved-rooms/")
    django_request.user = seeker

    view = MySavedRoomsView()
    request = view.initialize_request(django_request)
    request.user = seeker
    view.request = request

    # Fixed behaviour: evaluating the saved-room queryset is one SQL query,
    # and touching each room's landlord profile must not add per-room queries.
    with django_assert_num_queries(1):
        rooms = list(view.get_queryset())
        assert len(rooms) == 3

        for room in rooms:
            profile = room.property_owner.profile
            _ = profile.role_detail
            _ = profile.advertiser_verified
            _ = profile.allow_search_indexing_default
