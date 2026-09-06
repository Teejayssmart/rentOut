import pytest
from datetime import date, timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_different_landlords_can_use_same_room_title_without_409(django_user_model):
    landlord_one = django_user_model.objects.create_user(
        username="title_landlord_one",
        email="title_landlord_one@example.com",
        password="testpass123",
    )
    landlord_two = django_user_model.objects.create_user(
        username="title_landlord_two",
        email="title_landlord_two@example.com",
        password="testpass123",
    )

    payload = {
        "title": "Bright double room in shared flat",
        "description": (
            "This is a bright and spacious room with plenty of natural light, "
            "modern furnishings, fast broadband, secure entry, and excellent "
            "transport links to shops and the city centre."
        ),
        "location": "SW1A 1AA",
        "price_per_month": "800.00",
        "security_deposit": "800.00",
        "available_from": (date.today() + timedelta(days=30)).isoformat(),
        "availability_from_time": "10:00",
        "availability_to_time": "18:00",
        "view_available_days_mode": "everyday",
        "min_stay_months": 1,
        "max_stay_months": 6,
        "furnished": False,
        "bills_included": False,
        "property_type": "flat",
        "parking_available": False,
        "action": "next",
    }

    url = reverse("api:room-list")

    first_client = APIClient()
    first_client.force_authenticate(user=landlord_one)
    first_response = first_client.post(url, payload, format="json")
    assert first_response.status_code == status.HTTP_201_CREATED, first_response.data

    second_client = APIClient()
    second_client.force_authenticate(user=landlord_two)
    second_response = second_client.post(url, payload, format="json")

    assert second_response.status_code == status.HTTP_201_CREATED, second_response.data
    assert second_response.data.get("ok") is True
