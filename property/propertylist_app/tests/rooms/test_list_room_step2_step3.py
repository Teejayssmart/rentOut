import pytest

pytest_plugins = ["propertylist_app.tests.rooms.test_list_room_step1"]

from django.urls import reverse
from rest_framework import status

from propertylist_app.models import Room

from propertylist_app.models import Room


def _create_step1_room(auth_client, valid_step1_payload):
    """
    Helper: simulate Step 1 (NEXT) to create a room and return the Room instance.
    Uses the same pattern as the Step 1 tests: POST /api/rooms/ with action="next".
    """
    url = reverse("api:room-list")

    payload = {
        **valid_step1_payload,
        "action": "next",
    }

    response = auth_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data

    room_id = response.data["id"]
    return Room.objects.get(pk=room_id)


@pytest.mark.django_db
def test_step2_next_updates_room_partial_fields(auth_client, valid_step1_payload):
    """
    Step 2 – clicking NEXT:
    - Frontend sends PATCH to /api/rooms/<id>/ with extra fields + action="next"
    - Backend should accept partial update and return 200
    """
    room = _create_step1_room(auth_client, valid_step1_payload)

    url = reverse("api:room-detail", args=[room.id])

    patch_payload = {
        "description": "Updated description from step 2",
        "action": "next",
    }

    response = auth_client.patch(url, patch_payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.data

    room.refresh_from_db()
    assert room.description == "Updated description from step 2"


@pytest.mark.django_db
def test_step2_save_and_close_updates_and_returns_200(auth_client, valid_step1_payload):
    """
    Step 2 – clicking SAVE & CLOSE:
    - Same PATCH endpoint, but action='save_close'
    - Backend does the same update; FE decides to go back to dashboard.
    """
    room = _create_step1_room(auth_client, valid_step1_payload)

    url = reverse("api:room-detail", args=[room.id])

    patch_payload = {
        "description": "Draft description saved from step 2",
        "action": "save_close",
    }

    response = auth_client.patch(url, patch_payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.data

    room.refresh_from_db()
    assert room.description == "Draft description saved from step 2"


@pytest.mark.django_db
def test_step3_next_sets_location(auth_client, valid_step1_payload):
    """
    Step 3 – clicking NEXT:
    - PATCH /api/rooms/<id>/ with location fields + action='next'
    - Room.location should be updated.
    """
    room = _create_step1_room(auth_client, valid_step1_payload)

    url = reverse("api:room-detail", args=[room.id])

    patch_payload = {
        "location": "London",
        "action": "next",
    }

    response = auth_client.patch(url, patch_payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.data

    room.refresh_from_db()
    assert room.location == "London"


@pytest.mark.django_db
def test_step3_save_and_close_sets_location(auth_client, valid_step1_payload):
    """
    Step 3 – clicking SAVE & CLOSE:
    - Same PATCH endpoint, action='save_close'
    - Location is saved; FE chooses to exit the wizard.
    """
    room = _create_step1_room(auth_client, valid_step1_payload)

    url = reverse("api:room-detail", args=[room.id])

    patch_payload = {
        "location": "Manchester",
        "action": "save_close",
    }

    response = auth_client.patch(url, patch_payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.data

    room.refresh_from_db()
    assert room.location == "Manchester"
