import pytest
from datetime import date, timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from propertylist_app.models import Room, AvailabilitySlot, Booking


# --- Local fixtures so this file is self-contained ---


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def landlord_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="patch_landlord",
        email="patch_landlord@example.com",
        password="testpass123",
    )
    return user


@pytest.fixture
def auth_client(api_client, landlord_user):
    api_client.force_authenticate(user=landlord_user)
    return api_client


@pytest.fixture
def valid_step1_payload():
    future_available_from = (date.today() + timedelta(days=30)).isoformat()

    return {
        "title": "Patch test room",
        "description": "This is a bright and spacious room with plenty of natural light, modern furnishings, fast broadband, secure entry, and excellent transport links to shops and the city centre.",
        "location": "SW1A 1AA",
        "price_per_month": "800.00",
        "security_deposit": "800.00",
        "available_from": future_available_from,
        "availability_from_time": "10:00",
        "availability_to_time": "18:00",
        "view_available_days_mode": "everyday",
        "min_stay_months": 1,
        "max_stay_months": 6,
        "furnished": False,
        "bills_included": False,
        "property_type": "flat",
        "parking_available": False,
    }


# 1) PATCH: single-side time window should still be rejected
#    (same rule as POST, but using instance fallback logic)


@pytest.mark.django_db
def test_patch_availability_time_single_side_invalid(auth_client, valid_step1_payload):
    url_list = reverse("api:room-list")

    # First create a room with NO time window at all
    create_payload = {
        **valid_step1_payload,
        "action": "next",
    }
    create_payload.pop("availability_from_time", None)
    create_payload.pop("availability_to_time", None)

    create_resp = auth_client.post(url_list, create_payload, format="json")
    assert create_resp.status_code == status.HTTP_201_CREATED, create_resp.data

    room_id = create_resp.data["data"]["id"]
    url_detail = reverse("api:room-detail", args=[room_id])

    # PATCH only start time -> should complain about missing end time
    patch_resp = auth_client.patch(
        url_detail,
        {"availability_from_time": "09:00"},
        format="json",
    )
    assert patch_resp.status_code == status.HTTP_400_BAD_REQUEST

    # reason: variable is patch_resp (not response) and A4 envelope puts field errors under "field_errors"
    err = patch_resp.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "availability_to_time" in err.get("field_errors", {})



    # PATCH only end time -> should complain about missing start time
    patch_resp2 = auth_client.patch(
        url_detail,
        {"availability_to_time": "20:00"},
        format="json",
    )
    assert patch_resp2.status_code == status.HTTP_400_BAD_REQUEST

    err2 = patch_resp2.data
    assert err2.get("ok") is False
    assert err2.get("code") == "validation_error"
    assert "availability_from_time" in err2.get("field_errors", {})



# 2) PATCH: switch from everyday -> custom WITHOUT dates = error
#    (same rule as POST: custom mode requires at least one date)







@pytest.mark.django_db
def test_patch_switch_to_custom_without_dates_rejected(auth_client, valid_step1_payload):
    url_list = reverse("api:room-list")

    # Create as everyday (no custom dates)
    create_payload = {
        **valid_step1_payload,
        "view_available_days_mode": "everyday",
        "action": "next",
    }
    create_resp = auth_client.post(url_list, create_payload, format="json")
    assert create_resp.status_code == status.HTTP_201_CREATED, create_resp.data

    room_id = create_resp.data["data"]["id"]
    url_detail = reverse("api:room-detail", args=[room_id])

    # PATCH to custom but do NOT send view_available_custom_dates
    patch_resp = auth_client.patch(
        url_detail,
        {"view_available_days_mode": "custom"},
        format="json",
    )

    assert patch_resp.status_code == status.HTTP_400_BAD_REQUEST
    # reason: A4 error envelope stores field-level validation errors under "field_errors"
    err = patch_resp.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "view_available_custom_dates" in err.get("field_errors", {})



# 3) PATCH: switch from custom with dates -> everyday clears custom dates
#    (same behaviour as POST where non-custom modes ignore dates)


@pytest.mark.django_db
def test_patch_switch_from_custom_to_everyday_clears_dates(auth_client, valid_step1_payload):
    url_list = reverse("api:room-list")

    # Create as custom with some dates
    future1 = (date.today() + timedelta(days=10)).isoformat()
    future2 = (date.today() + timedelta(days=12)).isoformat()

    create_payload = {
        **valid_step1_payload,
        "view_available_days_mode": "custom",
        "view_available_custom_dates": [future1, future2],
        "action": "next",
    }
    create_resp = auth_client.post(url_list, create_payload, format="json")
    assert create_resp.status_code == status.HTTP_201_CREATED, create_resp.data

    room_id = create_resp.data["data"]["id"]
    url_detail = reverse("api:room-detail", args=[room_id])

    # PATCH to everyday – no need to send custom dates
    patch_resp = auth_client.patch(
        url_detail,
        {"view_available_days_mode": "everyday"},
        format="json",
    )
    assert patch_resp.status_code == status.HTTP_200_OK, patch_resp.data

    # Reload from DB and verify dates cleared
    room = Room.objects.get(pk=room_id)
    assert room.view_available_days_mode == "everyday"
    assert room.view_available_custom_dates == []
    
    
    
@pytest.mark.django_db
def test_patch_room_with_cancelled_booking_on_old_slot_does_not_return_409(
    auth_client,
    landlord_user,
    valid_step1_payload,
):
    url_list = reverse("api:room-list")

    create_payload = {
        **valid_step1_payload,
        "action": "next",
    }

    create_resp = auth_client.post(
        url_list,
        create_payload,
        format="json",
    )

    assert create_resp.status_code == status.HTTP_201_CREATED, create_resp.data

    room_id = create_resp.data["data"]["id"]
    room = Room.objects.get(id=room_id)

    slot = (
        AvailabilitySlot.objects
        .filter(room=room)
        .order_by("start")
        .first()
    )

    assert slot is not None

    Booking.objects.create(
        user=landlord_user,
        room=room,
        slot=slot,
        start=slot.start,
        end=slot.end,
        status=Booking.STATUS_ACTIVE,
        canceled_at=slot.start,
        is_deleted=False,
    )

    url_detail = reverse(
        "api:room-detail",
        args=[room_id],
    )

    patch_resp = auth_client.patch(
        url_detail,
        {
            "title": "Updated patch test room",
        },
        format="json",
    )

    assert patch_resp.status_code == status.HTTP_200_OK, patch_resp.data

    room.refresh_from_db()

    assert room.title == "Updated patch test room"

    assert AvailabilitySlot.objects.filter(
        id=slot.id,
    ).exists()

    assert Booking.objects.filter(
        slot_id=slot.id,
    ).exists()
    
    
    
@pytest.mark.django_db
def test_unpublished_room_remains_accessible_to_owner_and_can_be_republished(
    auth_client,
    valid_step1_payload,
):
    url_list = reverse("api:room-list")

    create_payload = {
        **valid_step1_payload,
        "action": "next",
    }

    create_resp = auth_client.post(
        url_list,
        create_payload,
        format="json",
    )

    assert create_resp.status_code == status.HTTP_201_CREATED, create_resp.data

    room_id = create_resp.data["data"]["id"]
    
    room = Room.objects.get(id=room_id)
    room.paid_until = date.today() + timedelta(days=30)
    room.status = "active"
    room.save(update_fields=["paid_until", "status"])

    unpublish_url = reverse(
        "api:room-unpublish",
        args=[room_id],
    )

    unpublish_resp = auth_client.post(
        unpublish_url,
        {},
        format="json",
    )

    assert unpublish_resp.status_code == status.HTTP_200_OK, unpublish_resp.data
    assert unpublish_resp.data["data"]["status"] == "hidden"

    # Hidden room must still be returned in the owner's own room list.
    mine_url = reverse("api:rooms-mine")

    mine_resp = auth_client.get(mine_url)

    assert mine_resp.status_code == status.HTTP_200_OK, mine_resp.data

    mine_data = mine_resp.data

    if isinstance(mine_data, dict) and "results" in mine_data:
        mine_data = mine_data["results"]

    assert any(
        room["id"] == room_id
        for room in mine_data
    )

    # Owner must still be able to retrieve the hidden room directly.
    detail_url = reverse(
        "api:room-detail",
        args=[room_id],
    )

    get_resp = auth_client.get(detail_url)

    assert get_resp.status_code == status.HTTP_200_OK, get_resp.data

    # Owner must still be able to edit it while unpublished.
    patch_resp = auth_client.patch(
        detail_url,
        {
            "price_per_month": "850.00",
        },
        format="json",
    )

    assert patch_resp.status_code == status.HTTP_200_OK, patch_resp.data

    room = Room.objects.get(id=room_id)

    assert room.status == "hidden"
    assert str(room.price_per_month) == "850.00"

    # Owner can publish it again.
    publish_url = reverse(
        "api:room-publish",
        args=[room_id],
    )

    publish_resp = auth_client.post(
        publish_url,
        {},
        format="json",
    )

    assert publish_resp.status_code == status.HTTP_200_OK, publish_resp.data
    assert publish_resp.data["data"]["status"] == "active"

    room.refresh_from_db()

    assert room.status == "active"    