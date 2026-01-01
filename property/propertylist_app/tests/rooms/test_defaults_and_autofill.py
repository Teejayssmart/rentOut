import pytest
from datetime import date, timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from propertylist_app.models import Room


@pytest.fixture
def api_client():
    """
    Basic DRF client.
    """
    return APIClient()


@pytest.fixture
def landlord_user(django_user_model):
    """
    Simple landlord user for auth.
    """
    user = django_user_model.objects.create_user(
        username="landlord_user",
        email="landlord@example.com",
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
    Payload that matches the 'List a Room – Step 1' fields,
    using a future available_from date so validation passes.
    """
    future_available_from = (date.today() + timedelta(days=30)).isoformat()

    return {
        "title": "Nice double room in shared flat",
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


@pytest.mark.django_db
def test_step1_defaults_autofill(auth_client, valid_step1_payload, landlord_user):
    """
    After Step-1 create via the API:
    - the room is created
    - property_owner is the logged-in landlord
    - category is auto-set to the 'General' category
    """
    url = reverse("api:room-list")

    payload = {
        **valid_step1_payload,
        "action": "next",
        # No category_id on purpose: we want Room.save() to auto-fill it.
    }

    response = auth_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.data
    assert Room.objects.count() == 1

    room = Room.objects.first()
    assert room is not None

    # Owner should be the currently logged-in user
    assert room.property_owner == landlord_user

    # Category should have been auto-created as "General"
    assert room.category is not None
    assert room.category.name.lower() == "general"


@pytest.mark.django_db
def test_room_model_autofills_owner_and_category_when_missing(landlord_user):
    """
    Direct model-level test (no API):

    If we create a Room without:
    - property_owner
    - category

    then Room.save() should:
    - pick the first user in the DB as property_owner (landlord_user here)
    - create / attach the 'General' category automatically
    """
    room = Room.objects.create(
        title="Autofilled room",
        description="Simple room created directly from the model.",
        price_per_month="500.00",
        location="SW1A 2AA, London",
        property_type="flat",
        # Intentionally no property_owner and no category here.
    )

    room.refresh_from_db()

    # Owner auto-filled (first user in DB is landlord_user)
    assert room.property_owner == landlord_user

    # Category auto-filled to the 'General' category
    assert room.category is not None
    assert room.category.name.lower() == "general"
