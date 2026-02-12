import pytest
from datetime import date, timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from propertylist_app.models import Room


# ---- Local fixtures (so this file runs on its own) ----

@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def landlord_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="landlord_custom",
        email="landlord_custom@example.com",
        password="testpass123",
    )
    return user


@pytest.fixture
def auth_client(api_client, landlord_user):
    api_client.force_authenticate(user=landlord_user)
    return api_client


@pytest.fixture
def valid_step1_payload():
    """
    Same idea as in the other tests: a valid Step-1 payload
    that we can tweak for custom dates.
    """
    future_available_from = (date.today() + timedelta(days=30)).isoformat()

    return {
        "title": "Room with custom viewing dates",
        "description": "This is a bright and spacious room with plenty of natural light, modern furnishings, fast broadband, secure entry, and excellent transport links to shops and the city centre.",
        "location": "SW1A 1AA",
        "price_per_month": "800.00",
        "security_deposit": "800.00",
        "available_from": future_available_from,
        "availability_from_time": "10:00",
        "availability_to_time": "18:00",
        # default mode – we will override in tests
        "view_available_days_mode": "everyday",
        "min_stay_months": 1,
        "max_stay_months": 6,
        "furnished": False,
        "bills_included": False,
        "property_type": "flat",
        "parking_available": False,
    }


# ---- Tests for custom dates behaviour ----

@pytest.mark.django_db
def test_custom_mode_with_valid_dates_persists_dates(auth_client, valid_step1_payload):
    """
    mode = 'custom' + a non-empty list of dates:
    - Request should be 201
    - Room.view_available_custom_dates should contain those dates (normalised to strings).
    """
    url = reverse("api:room-list")

    d1 = (date.today() + timedelta(days=5)).isoformat()
    d2 = (date.today() + timedelta(days=7)).isoformat()

    payload = {
        **valid_step1_payload,
        "action": "next",
        "view_available_days_mode": "custom",
        "view_available_custom_dates": [d1, d2],
    }

    resp = auth_client.post(url, payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED, resp.data
    assert Room.objects.count() == 1

    room = Room.objects.first()
    assert room.view_available_days_mode == "custom"
    # Stored as list of strings
    assert room.view_available_custom_dates == [d1, d2]


@pytest.mark.django_db
def test_custom_mode_with_empty_dates_rejected(auth_client, valid_step1_payload):
    """
    mode = 'custom' + empty list:
    - Should return 400 with error on view_available_custom_dates.
    """
    url = reverse("api:room-list")

    payload = {
        **valid_step1_payload,
        "action": "next",
        "view_available_days_mode": "custom",
        "view_available_custom_dates": [],
    }

    resp = auth_client.post(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST

    err = resp.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "view_available_custom_dates" in err.get("field_errors", {})



@pytest.mark.django_db
def test_non_custom_mode_ignores_custom_dates(auth_client, valid_step1_payload):
    """
    If mode != 'custom' but custom dates are sent:
    - Request should succeed
    - Serializer should clear view_available_custom_dates to [].
    """
    url = reverse("api:room-list")

    d1 = (date.today() + timedelta(days=3)).isoformat()
    d2 = (date.today() + timedelta(days=10)).isoformat()

    payload = {
        **valid_step1_payload,
        "action": "next",
        "view_available_days_mode": "everyday",
        "view_available_custom_dates": [d1, d2],
    }

    resp = auth_client.post(url, payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED, resp.data
    assert Room.objects.count() == 1

    room = Room.objects.first()
    assert room.view_available_days_mode == "everyday"
    # Non-custom modes must end up with an empty list
    assert room.view_available_custom_dates == []


@pytest.mark.django_db
def test_custom_mode_with_bad_date_format_rejected(auth_client, valid_step1_payload):
    """
    mode = 'custom' + invalid date string:
    - Should return 400 with validation error.
    """
    url = reverse("api:room-list")

    bad_date = "2025/10/10"  # wrong format

    payload = {
        **valid_step1_payload,
        "action": "next",
        "view_available_days_mode": "custom",
        "view_available_custom_dates": [bad_date],
    }

    resp = auth_client.post(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST

    err = resp.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "view_available_custom_dates" in err.get("field_errors", {})

