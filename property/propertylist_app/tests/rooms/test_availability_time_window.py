import pytest
from datetime import date, timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from propertylist_app.models import Room


# ---------- Shared fixtures (local to this file) ----------

@pytest.fixture
def api_client():
    """
    Basic DRF client for these tests.
    """
    return APIClient()


@pytest.fixture
def landlord_user(django_user_model):
    """
    Simple landlord user for auth.
    """
    user = django_user_model.objects.create_user(
        username="landlord_user_time",
        email="landlord_time@example.com",
        password="testpass123",
    )
    return user


@pytest.fixture
def auth_client(api_client, landlord_user):
    """
    API client authenticated as the landlord user.
    """
    api_client.force_authenticate(user=landlord_user)
    return api_client


@pytest.fixture
def valid_step1_payload():
    """
    Base Step-1 payload with a valid future available_from date.
    """
    future_available_from = (date.today() + timedelta(days=30)).isoformat()

    return {
        "title": "Room with viewing window",
        "description": "This is a bright and spacious room with plenty of natural light, modern furnishings, fast broadband, secure entry, and excellent transport links to shops and the city centre.",
        "location": "SW1A 1AA",
        "price_per_month": "750.00",
        "security_deposit": "750.00",
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


# ---------- Tests for availability_from_time / availability_to_time ----------

@pytest.mark.django_db
def test_availability_time_valid_window(auth_client, valid_step1_payload):
    """
    If landlord sets a valid time window (start < end),
    the room is created and times are stored correctly.
    """
    url = reverse("api:room-list")

    payload = {
    **valid_step1_payload,
    "description": "This is a bright and spacious room in a quiet home with fast WiFi, bills included, and good transport links to shops and the city centre.",
    "location": "SW1A 1AA",
    "availability_from_time": "09:30",
    "availability_to_time": "17:45",
    "action": "next",
    }


    response = auth_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.data
    assert Room.objects.count() == 1

    room = Room.objects.first()
    # Stored as proper time objects – string form includes seconds
    assert str(room.availability_from_time) == "09:30:00"
    assert str(room.availability_to_time) == "17:45:00"


@pytest.mark.django_db
def test_availability_time_missing_end_time_rejected(auth_client, valid_step1_payload):
    """
    If only start time is provided, backend should reject:
    - availability_from_time present
    - availability_to_time missing
    → 400 with error on availability_to_time
    """
    url = reverse("api:room-list")

    payload = {
        **valid_step1_payload,
        "availability_from_time": "10:00",
        "action": "next",
    }
    # Ensure end time is *not* sent
    payload.pop("availability_to_time", None)

    response = auth_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "availability_to_time" in response.data


@pytest.mark.django_db
def test_availability_time_missing_start_time_rejected(auth_client, valid_step1_payload):
    """
    If only end time is provided, backend should reject:
    - availability_to_time present
    - availability_from_time missing
    → 400 with error on availability_from_time
    """
    url = reverse("api:room-list")

    payload = {
        **valid_step1_payload,
        "availability_to_time": "18:00",
        "action": "next",
    }
    # Ensure start time is *not* sent
    payload.pop("availability_from_time", None)

    response = auth_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "availability_from_time" in response.data


@pytest.mark.django_db
def test_availability_time_end_before_start_rejected(auth_client, valid_step1_payload):
    """
    If end time is not after start time (start >= end),
    backend should reject with an error on availability_to_time.
    """
    url = reverse("api:room-list")

    payload = {
        **valid_step1_payload,
        "availability_from_time": "18:00",
        "availability_to_time": "10:00",
        "action": "next",
    }

    response = auth_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "availability_to_time" in response.data
