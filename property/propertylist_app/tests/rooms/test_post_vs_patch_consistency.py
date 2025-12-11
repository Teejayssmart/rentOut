import pytest
from datetime import date, timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from propertylist_app.models import Room


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
        "description": "Room for POST vs PATCH tests.",
        "price_per_month": "800.00",
        "security_deposit": "800.00",
        "location": "SW1A 1AA, London",
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

    room_id = create_resp.data["id"]
    url_detail = reverse("api:room-detail", args=[room_id])

    # PATCH only start time -> should complain about missing end time
    patch_resp = auth_client.patch(
        url_detail,
        {"availability_from_time": "09:00"},
        format="json",
    )
    assert patch_resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "availability_to_time" in patch_resp.data

    # PATCH only end time -> should complain about missing start time
    patch_resp2 = auth_client.patch(
        url_detail,
        {"availability_to_time": "20:00"},
        format="json",
    )
    assert patch_resp2.status_code == status.HTTP_400_BAD_REQUEST
    assert "availability_from_time" in patch_resp2.data


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

    room_id = create_resp.data["id"]
    url_detail = reverse("api:room-detail", args=[room_id])

    # PATCH to custom but do NOT send view_available_custom_dates
    patch_resp = auth_client.patch(
        url_detail,
        {"view_available_days_mode": "custom"},
        format="json",
    )

    assert patch_resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "view_available_custom_dates" in patch_resp.data


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

    room_id = create_resp.data["id"]
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
