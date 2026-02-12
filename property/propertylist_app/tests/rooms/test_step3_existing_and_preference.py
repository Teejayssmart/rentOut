import pytest
from datetime import date, timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from propertylist_app.models import Room


# -------------------------------------------------------------------
# Shared fixtures (same pattern as your Step-1 tests)
# -------------------------------------------------------------------
@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def landlord_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="landlord_step3",
        email="landlord_step3@example.com",
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
    Minimal Step-1 payload that passes your RoomSerializer + model validation.
    Used to create a draft room before we PATCH Step-3 fields.
    """
    future_available_from = (date.today() + timedelta(days=30)).isoformat()

    return {
        "title": "Step3 test room",
        # >>> LONG DESCRIPTION (>= 25 words) <<<
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


@pytest.fixture
def draft_room(auth_client, valid_step1_payload):
    """
    Create a room via Step-1 (POST /api/rooms/) and return the instance.
    Step-3 will always PATCH this same room.
    """
    url = reverse("api:room-list")
    payload = {**valid_step1_payload, "action": "next"}
    response = auth_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data

    room_id = response.data["id"]
    return Room.objects.get(id=room_id)


# -------------------------------------------------------------------
# Step 3/5 – Existing flatmate section
# -------------------------------------------------------------------
@pytest.mark.django_db
def test_step3_existing_flatmate_happy_path(auth_client, draft_room):
    """
    User fills in the Existing Flatmate section with valid values.
    PATCH should succeed and values should be stored on the Room.
    """
    url = reverse("api:room-detail", args=[draft_room.id])

    payload = {
        "existing_flatmate_age": 28,
        "existing_flatmate_nationality": "Spanish",
        "existing_flatmate_language": "English",
        "existing_flatmate_gender": "male",
        "existing_flatmate_occupation": "professional",
        "existing_flatmate_smoking": "no",
        "existing_flatmate_pets": "yes",
        "existing_flatmate_lgbtqia_household": "no_preference",
    }

    response = auth_client.patch(url, payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.data

    draft_room.refresh_from_db()
    assert draft_room.existing_flatmate_age == 28
    assert draft_room.existing_flatmate_nationality == "Spanish"
    assert draft_room.existing_flatmate_language == "English"
    assert draft_room.existing_flatmate_gender == "male"
    assert draft_room.existing_flatmate_occupation == "professional"
    assert draft_room.existing_flatmate_smoking == "no"
    assert draft_room.existing_flatmate_pets == "yes"
    assert draft_room.existing_flatmate_lgbtqia_household == "no_preference"


@pytest.mark.django_db
def test_step3_existing_flatmate_rejects_invalid_gender(auth_client, draft_room):
    """
    Existing flatmate gender must match the defined choices.
    An invalid value like 'robot' should be rejected with 400.
    """
    url = reverse("api:room-detail", args=[draft_room.id])

    payload = {
        "existing_flatmate_gender": "robot",
    }

    response = auth_client.patch(url, payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    err = response.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "existing_flatmate_gender" in err.get("field_errors", {})



@pytest.mark.django_db
def test_step3_existing_flatmate_rejects_invalid_smoking_choice(auth_client, draft_room):
    """
    Smoking, pets and LGBTQIA+ household use YES/NO/NO_PREFERENCE.
    An unknown value should be rejected.
    """
    url = reverse("api:room-detail", args=[draft_room.id])

    payload = {
        "existing_flatmate_smoking": "maybe",
    }

    response = auth_client.patch(url, payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    err = response.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "existing_flatmate_smoking" in err.get("field_errors", {})



# -------------------------------------------------------------------
# Step 3/5 – Flatmate preference section
# -------------------------------------------------------------------
@pytest.mark.django_db
def test_step3_flatmate_preference_happy_path(auth_client, draft_room):
    """
    User sets preferred flatmate nationality, language, age range and
    other preferences. PATCH should succeed and persist values.
    """
    url = reverse("api:room-detail", args=[draft_room.id])

    payload = {
        "preferred_flatmate_nationality": "French",
        "preferred_flatmate_language": "French",
        "preferred_flatmate_min_age": 21,
        "preferred_flatmate_max_age": 35,
        "preferred_flatmate_occupation": "open_to_everyone",
        "preferred_flatmate_pets": "no_preference",
        "preferred_flatmate_gender": "no_preference",
        "preferred_flatmate_smoking": "no",
        "preferred_flatmate_partners_allowed": "yes",
        "preferred_flatmate_lgbtqia": "yes",
        "preferred_flatmate_vegan_vegetarian": "no_preference",
    }

    response = auth_client.patch(url, payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.data

    draft_room.refresh_from_db()
    assert draft_room.preferred_flatmate_nationality == "French"
    assert draft_room.preferred_flatmate_language == "French"
    assert draft_room.preferred_flatmate_min_age == 21
    assert draft_room.preferred_flatmate_max_age == 35
    assert draft_room.preferred_flatmate_occupation == "open_to_everyone"
    assert draft_room.preferred_flatmate_pets == "no_preference"
    assert draft_room.preferred_flatmate_gender == "no_preference"
    assert draft_room.preferred_flatmate_smoking == "no"
    assert draft_room.preferred_flatmate_partners_allowed == "yes"
    assert draft_room.preferred_flatmate_lgbtqia == "yes"
    assert draft_room.preferred_flatmate_vegan_vegetarian == "no_preference"


@pytest.mark.django_db
def test_step3_flatmate_preference_invalid_age_range_rejected(auth_client, draft_room):
    """
    Min & Max Age: backend should reject min > max.
    """
    url = reverse("api:room-detail", args=[draft_room.id])

    payload = {
        "preferred_flatmate_min_age": 40,
        "preferred_flatmate_max_age": 25,
    }

    response = auth_client.patch(url, payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    err = response.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "preferred_flatmate_min_age" in err.get("field_errors", {})



@pytest.mark.django_db
def test_step3_flatmate_preference_invalid_gender_choice_rejected(auth_client, draft_room):
    """
    Preferred flatmate gender must be one of:
    no_preference / male / female / others.
    """
    url = reverse("api:room-detail", args=[draft_room.id])

    payload = {
        "preferred_flatmate_gender": "alien",
    }

    response = auth_client.patch(url, payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    err = response.data
    assert err.get("ok") is False
    assert err.get("code") == "validation_error"
    assert "preferred_flatmate_gender" in err.get("field_errors", {})

