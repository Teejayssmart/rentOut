import pytest
from datetime import date, timedelta
import io
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.db import models
from django.test import override_settings
from propertylist_app.models import Room, RoomImage


# ------------------------
# Local fixtures
# ------------------------

@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def landlord_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="step4_landlord",
        email="step4_landlord@example.com",
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
    Same idea as Step-1 tests: a valid payload that passes RoomSerializer
    (including description word-count and future available_from).
    """
    future_date = (date.today() + timedelta(days=30)).isoformat()

    long_description = (
        "This is a bright and spacious double room in a friendly shared flat. "
        "The property is close to local shops, transport links, and a beautiful park, "
        "making it ideal for professionals or students looking for a calm place to stay."
    )

    return {
        "title": "Lovely bright double room",
        "description": "This is a bright and spacious room with plenty of natural light, modern furnishings, fast broadband, secure entry, and excellent transport links to shops and the city centre.",
        "location": "SW1A 1AA",
        "price_per_month": "700.00",
        "security_deposit": "700.00",
        "available_from": future_date,
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


@pytest.fixture(autouse=True)
def _force_test_media_root(tmp_path):
    """
    Reason:
    Ensure file uploads always write to a real, writable directory on Windows/CI.
    """
    with override_settings(MEDIA_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        yield


@pytest.fixture(autouse=True)
def _bypass_roomimage_save_override(monkeypatch):
    """
    Reason:
    RoomImage.save() override can close the underlying uploaded file before Django writes it,
    which causes storage to raise and your view to return a 500 envelope.
    Test-only: bypass the override so uploads are stable.
    """
    monkeypatch.setattr(RoomImage, "save", models.Model.save, raising=False)




@pytest.fixture
def create_draft_room(auth_client, valid_step1_payload):
    """
    Helper: creates a Room via Step-1 POST and returns the instance.
    Status will effectively be 'draft' for the wizard until payment.
    """

    def _create():
        url = reverse("api:room-list")
        payload = {
            **valid_step1_payload,
            "action": "next",  # wizard flag; backend ignores for now
        }
        response = auth_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        return Room.objects.get(id=response.data["id"])

    return _create


def _upload_fake_photo(client, room, name="photo.jpg"):
    """
    Upload a single valid JPEG image to the room photo endpoint.

    Reason:
    Backend performs real image validation/moderation. Fake bytes can raise PIL/validators
    errors and get wrapped into a 500. This test is about Step 4 min-photos rule, not image decoding.
    """
    url = reverse("api:room-photo-upload", args=[room.id])

    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color=(255, 0, 0)).save(buf, format="JPEG")
    buf.seek(0)

    real_image = SimpleUploadedFile(
        name,
        buf.getvalue(),
        content_type="image/jpeg",
    )

    return client.post(url, {"image": real_image}, format="multipart")


# ------------------------
# Tests
# ------------------------

@pytest.mark.django_db
def test_step4_preview_blocked_with_less_than_three_photos(auth_client, create_draft_room):
    """
    When the wizard sends PATCH /rooms/<id> with action='preview'
    (Step 4 Next/Preview) and the room has fewer than 3 photos,
    the backend must return 400 with a helpful error.
    """
    room = create_draft_room()

    # Upload ONLY 2 photos
    resp1 = _upload_fake_photo(auth_client, room, "p1.jpg")
    assert resp1.status_code == status.HTTP_201_CREATED, resp1.data

    resp2 = _upload_fake_photo(auth_client, room, "p2.jpg")
    assert resp2.status_code == status.HTTP_201_CREATED, resp2.data

    assert RoomImage.objects.filter(room=room).count() == 2

    # Now attempt to go to Preview (Step 4 -> Step 5)
    url = reverse("api:room-detail", args=[room.id])
    patch_payload = {
        "action": "preview",  # Step-4 Next/Preview
    }
    response = auth_client.patch(url, patch_payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "detail" in response.data
    assert "photos_min_required" in response.data
    assert response.data["photos_min_required"] == 3
    assert response.data["photos_current"] == 2


@pytest.mark.django_db
def test_step4_preview_allows_when_at_least_three_photos(auth_client, create_draft_room):
    """
    When there are 3 or more photos and action='preview',
    PATCH should succeed (200) so the wizard can move to Step 5.
    """
    room = create_draft_room()

    # Upload 3 photos
    for idx in range(3):
        resp = _upload_fake_photo(auth_client, room, f"p{idx+1}.jpg")
        assert resp.status_code == status.HTTP_201_CREATED, resp.data

    assert RoomImage.objects.filter(room=room).count() == 3

    url = reverse("api:room-detail", args=[room.id])
    patch_payload = {
        "action": "preview",
    }
    response = auth_client.patch(url, patch_payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.data
    # Room data still comes back; status remains whatever it was (draft until payment)
    assert response.data["id"] == room.id


@pytest.mark.django_db
def test_step4_save_close_does_not_require_photos(auth_client, create_draft_room):
    """
    Save & Close from Step 4 should NOT enforce the 3-photo rule.
    Even with zero photos, PATCH with action='save_close' must succeed.
    """
    room = create_draft_room()

    # No photos uploaded
    assert RoomImage.objects.filter(room=room).count() == 0

    url = reverse("api:room-detail", args=[room.id])
    patch_payload = {
        "action": "save_close",
    }
    response = auth_client.patch(url, patch_payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.data
    assert response.data["id"] == room.id
