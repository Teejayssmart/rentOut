from datetime import timedelta

import pytest
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from propertylist_app.api.serializers import RoomSerializer
from propertylist_app.models import Room, RoomCategorie, RoomImage


@pytest.mark.django_db
def test_room_serializer_loads_room_images_only_once(
    django_user_model,
    django_assert_num_queries,
):
    landlord = django_user_model.objects.create_user(
        username="serializer_perf_landlord",
        email="serializer_perf_landlord@example.com",
        password="testpass123",
    )
    category = RoomCategorie.objects.create(
        name="Serializer perf",
        active=True,
    )
    room = Room.objects.create(
        title="Serializer performance room",
        description="A room used to prove that serializing one listing does not query the same photos repeatedly.",
        location="SO14 0AA",
        price_per_month=700,
        security_deposit=700,
        property_owner=landlord,
        category=category,
        status="active",
        is_available=True,
        paid_until=timezone.localdate() + timedelta(days=30),
    )

    for index in range(3):
        RoomImage.objects.create(
            room=room,
            image=f"room_images/serializer-performance-{index}.jpg",
            status=RoomImage.STATUS_APPROVED,
        )

    # Load every non-photo relation before measuring. The assertion below is
    # intentionally about the RoomImage work done by RoomSerializer itself.
    room = Room.objects.select_related(
        "category",
        "property_owner",
        "property_owner__profile",
    ).get(pk=room.pk)

    request = APIRequestFactory().get("/api/v1/rooms/performance-check/")
    request.user = AnonymousUser()
    serializer = RoomSerializer(room, context={"request": request})

    # cover_image, other_images, image_status and listing_state all need the
    # same photo set. One room must therefore cause one RoomImage query, not
    # one fresh query for every serializer field.
    with django_assert_num_queries(1):
        data = serializer.data

    assert data["cover_image"]
    assert len(data["other_images"]) == 2
    assert data["image_status"] == "approved"
    assert data["listing_state"] == "active"
