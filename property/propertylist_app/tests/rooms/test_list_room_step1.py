import pytest
from datetime import date, timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

# Use your existing Room model from models.py (do not touch models.py)
from propertylist_app.models import Room


@pytest.fixture
def api_client():
    """
    Basic DRF client.

    If you already have an api_client fixture in property/propertylist_app/tests/conftest.py,
    you can delete this fixture from here and keep the one in conftest.py.
    """
    return APIClient()


@pytest.fixture
def landlord_user(django_user_model):
    """
    Simple landlord user for auth.
    If you already have a landlord_user fixture, you can remove this one.
    """
    user = django_user_model.objects.create_user(
        username="landlord_user",
        email="landlord@example.com",
        password="testpass123",
    )
    # If you use a role flag on UserProfile etc., set it here if needed.
    return user


@pytest.fixture
def auth_client(api_client, landlord_user):
    """
    API client authenticated as the landlord user.
    Adjust if you use JWT tokens instead of force_authenticate.
    """
    api_client.force_authenticate(user=landlord_user)
    return api_client


@pytest.fixture
def valid_step1_payload():
    """
    Payload that matches the 'List a Room – Step 1' fields
    based on your Room model.

    Mapping from the Figma form to backend fields:

    - Monthly Rent           -> price_per_month
    - Security Deposit       -> security_deposit
    - View Available Days    -> view_available_days_mode
    - Availability Start     -> availability_from_time
    - Availability Stop      -> availability_to_time
    - List Available Date    -> available_from
    - Minimum Rental Period  -> min_stay_months
    - Maximum Rental Period  -> max_stay_months

    NOTE: available_from must NOT be in the past, so we always
    use a date 30 days in the future from “today”.
    """
    future_available_from = (date.today() + timedelta(days=30)).isoformat()

    return {
        "title": "Nice double room in shared flat",
        "description": "This is a bright and spacious room with plenty of natural light, modern furnishings, fast broadband, secure entry, and excellent transport links to shops and the city centre.",
        "location": "SW1A 1AA",
        "price_per_month": "750.00",
        "security_deposit": "750.00",
        # Always future so Room.clean() doesn’t reject it
        "available_from": future_available_from,

        "availability_from_time": "10:00",
        "availability_to_time": "18:00",

        # View Available Days dropdown (everyday / weekdays / weekends / custom)
        "view_available_days_mode": "everyday",

        # If mode = 'custom' you would also send view_available_custom_dates as a list
        # "view_available_custom_dates": ["2025-10-20", "2025-10-22"],

        # rental period in months
        "min_stay_months": 1,
        "max_stay_months": 6,

        # some extra safe defaults required by Room model
        "furnished": False,
        "bills_included": False,
        "property_type": "flat",   # one of: flat / house / studio
        "parking_available": False,
    }



# -------------------------------------------------
# Tests for List-a-Room STEP 1 (Basic Information)
# -------------------------------------------------

@pytest.mark.django_db
def test_step1_next_creates_room_and_returns_201(auth_client, valid_step1_payload):
    """
    When landlord fills Step 1 and clicks NEXT:
    - Room is created in DB
    - HTTP 201 is returned
    - property_owner is set to the logged-in user
    """
    url = reverse("api:room-list")

    payload = {
        **valid_step1_payload,
        "action": "next",
    }

    response = auth_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.data

    assert Room.objects.count() == 1
    room = Room.objects.first()

    assert room.title == valid_step1_payload["title"]
    assert str(room.price_per_month) == valid_step1_payload["price_per_month"]
    assert room.property_owner is not None


@pytest.mark.django_db
def test_step1_save_and_close_saves_draft_room(auth_client, valid_step1_payload):
    """
    When landlord clicks SAVE & CLOSE:
    - Room is saved
    - Response is 200 or 201 (depending on implementation)
    """
    url = reverse("api:room-list")

    payload = {
        **valid_step1_payload,
        "action": "save_close",
    }

    response = auth_client.post(url, payload, format="json")

    assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), response.data
    assert Room.objects.count() == 1


@pytest.mark.django_db
def test_step1_missing_price_returns_400(auth_client, valid_step1_payload):
    """
    If the Monthly Rent (price_per_month) is missing, the API should reject the request.
    """
    url = reverse("api:room-list")

    bad_payload = valid_step1_payload.copy()
    bad_payload.pop("price_per_month")
    bad_payload["action"] = "next"

    response = auth_client.post(url, bad_payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "price_per_month" in response.data


@pytest.mark.django_db
def test_step1_negative_price_returns_400(auth_client, valid_step1_payload):
    """
    Negative Monthly Rent should fail validation.
    """
    url = reverse("api:room-list")

    bad_payload = {
        **valid_step1_payload,
        "price_per_month": "-10.00",
        "action": "next",
    }

    response = auth_client.post(url, bad_payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "price_per_month" in response.data


# -------------------------------------------------
# Extra validations – REQUIRED FIELDS & FORMATS
# -------------------------------------------------

@pytest.mark.django_db
def test_step1_missing_title_returns_400(auth_client, valid_step1_payload):
    """
    Title is required.
    """
    url = reverse("api:room-list")

    bad_payload = valid_step1_payload.copy()
    bad_payload.pop("title")
    bad_payload["action"] = "next"

    response = auth_client.post(url, bad_payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "title" in response.data


@pytest.mark.django_db
def test_step1_missing_location_returns_400(auth_client, valid_step1_payload):
    """
    Location / postcode is required.
    """
    url = reverse("api:room-list")

    bad_payload = valid_step1_payload.copy()
    bad_payload.pop("location")
    bad_payload["action"] = "next"

    response = auth_client.post(url, bad_payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "location" in response.data


@pytest.mark.django_db
def test_step1_negative_security_deposit_returns_400(auth_client, valid_step1_payload):
    """
    Security deposit cannot be negative.
    """
    url = reverse("api:room-list")

    bad_payload = {
        **valid_step1_payload,
        "security_deposit": "-100.00",
        "action": "next",
    }

    response = auth_client.post(url, bad_payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "security_deposit" in response.data


@pytest.mark.django_db
def test_step1_invalid_available_from_format_returns_400(auth_client, valid_step1_payload):
    """
    available_from must be a valid date in YYYY-MM-DD format.
    """
    url = reverse("api:room-list")

    bad_payload = {
        **valid_step1_payload,
        "available_from": "15-10-2025",  # wrong format
        "action": "next",
    }

    response = auth_client.post(url, bad_payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "available_from" in response.data


@pytest.mark.django_db
def test_step1_invalid_time_format_returns_400(auth_client, valid_step1_payload):
    """
    Availability times must be valid HH:MM.
    """
    url = reverse("api:room-list")

    bad_payload = {
        **valid_step1_payload,
        "availability_from_time": "25:00",  # invalid hour
        "action": "next",
    }

    response = auth_client.post(url, bad_payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "availability_from_time" in response.data


# -------------------------------------------------
# Business rules (min/max stay, bills + price)
# -------------------------------------------------

@pytest.mark.django_db
def test_step1_min_stay_cannot_be_greater_than_max_stay(auth_client, valid_step1_payload):
    """
    min_stay_months > max_stay_months should fail validation.
    """
    url = reverse("api:room-list")

    bad_payload = {
        **valid_step1_payload,
        "min_stay_months": 6,
        "max_stay_months": 3,
        "action": "next",
    }

    response = auth_client.post(url, bad_payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "min_stay_months" in response.data


@pytest.mark.django_db
def test_step1_bills_included_for_very_low_price_rejected(auth_client, valid_step1_payload):
    """
    Model rule: if bills_included is True and price_per_month < 100,
    validation should fail.
    """
    url = reverse("api:room-list")

    bad_payload = {
        **valid_step1_payload,
        "price_per_month": "50.00",
        "bills_included": True,
        "action": "next",
    }

    response = auth_client.post(url, bad_payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    # error could be attached to 'bills_included' by the Room.clean()
    assert "bills_included" in response.data



@pytest.mark.django_db
def test_view_available_days_everyday_mode_sets_empty_custom_dates(auth_client, valid_step1_payload):
    """
    Mode = 'everyday':
    - We send view_available_days_mode='everyday'
    - No custom dates
    - Room should save with mode='everyday' and view_available_custom_dates = []
    """
    url = reverse("api:room-list")

    payload = {
        **valid_step1_payload,
        "action": "next",
        "view_available_days_mode": "everyday",
        # we deliberately omit view_available_custom_dates
    }

    response = auth_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data

    room_id = response.data["id"]
    room = Room.objects.get(pk=room_id)

    assert room.view_available_days_mode == "everyday"
    assert room.view_available_custom_dates == []


@pytest.mark.django_db
def test_view_available_days_custom_mode_with_valid_dates(auth_client, valid_step1_payload):
    """
    Mode = 'custom' with valid dates:
    - send non-empty view_available_custom_dates list
    - Room should save with those dates normalised as ISO strings.
    """
    url = reverse("api:room-list")

    custom_dates = ["2025-12-01", "2025-12-03", "2025-12-10"]

    payload = {
        **valid_step1_payload,
        "action": "next",
        "view_available_days_mode": "custom",
        "view_available_custom_dates": custom_dates,
    }

    response = auth_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data

    room_id = response.data["id"]
    room = Room.objects.get(pk=room_id)

    assert room.view_available_days_mode == "custom"
    # Stored as list of strings in JSONField
    assert room.view_available_custom_dates == custom_dates


@pytest.mark.django_db
def test_view_available_days_custom_mode_requires_at_least_one_date(auth_client, valid_step1_payload):
    """
    Mode = 'custom' but empty dates:
    - Should return 400
    - Error attached to view_available_custom_dates
    """
    url = reverse("api:room-list")

    payload = {
        **valid_step1_payload,
        "action": "next",
        "view_available_days_mode": "custom",
        "view_available_custom_dates": [],
    }

    response = auth_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "view_available_custom_dates" in response.data
