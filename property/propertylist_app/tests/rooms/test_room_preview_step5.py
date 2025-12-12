import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model

from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, RoomImage

User = get_user_model()


@pytest.mark.django_db
def test_owner_can_see_room_preview_with_photos(tmp_path, settings):
    """
    Step 5/5 – owner can load the preview endpoint and see:
      - 'room' object with core fields (title, location, price_per_month)
      - 'photos' list populated from approved RoomImage objects.
    """
    # Make MEDIA_ROOT writable in test
    settings.MEDIA_ROOT = tmp_path

    # Create owner + category
    owner = User.objects.create_user(
        username="owner1", email="owner1@example.com", password="pass1234"
    )
    cat = RoomCategorie.objects.create(name="General")

    # Create a draft room for this owner
    room = Room.objects.create(
        title="Nice double room",
        description="A " + "very nice room " * 20,  # pass description min-words rule
        price_per_month=750,
        security_deposit=200,
        location="10 Test Street London SW1A 1AA",
        category=cat,
        property_owner=owner,
        status="draft",
    )

    # Attach some approved photos
    # We don't care about the actual file contents here, only that a path exists.
    RoomImage.objects.create(room=room, image="room_images/photo1.jpg", status="approved")
    RoomImage.objects.create(room=room, image="room_images/photo2.jpg", status="approved")

    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("api:room-preview", kwargs={"pk": room.pk})
    response = client.get(url)

    assert response.status_code == 200

    data = response.json()
    assert "room" in data
    assert "photos" in data

    # Basic room fields visible
    assert data["room"]["id"] == room.pk
    assert data["room"]["title"] == "Nice double room"
    assert data["room"]["location"] == room.location
    assert str(data["room"]["price_per_month"]) == "750.00"

    # Photos should come from RoomImage and be at least 2
    assert len(data["photos"]) == 2
    for photo in data["photos"]:
        assert "id" in photo
        assert "url" in photo
        assert "status" in photo
        assert photo["status"] == "approved"


@pytest.mark.django_db
def test_non_owner_cannot_see_room_preview():
    """
    Only the property owner is allowed to access the preview payload.
    A different authenticated user should receive 403 Forbidden.
    """
    owner = User.objects.create_user(
        username="owner2", email="owner2@example.com", password="pass1234"
    )
    other = User.objects.create_user(
        username="other", email="other@example.com", password="pass1234"
    )
    cat = RoomCategorie.objects.create(name="General")

    room = Room.objects.create(
        title="Owner only preview",
        description="A " + "very nice room " * 20,
        price_per_month=500,
        security_deposit=150,
        location="20 Test Street London SW1A 1AA",
        category=cat,
        property_owner=owner,
        status="draft",
    )

    client = APIClient()
    client.force_authenticate(user=other)

    url = reverse("api:room-preview", kwargs={"pk": room.pk})
    response = client.get(url)

    assert response.status_code == 403



@pytest.mark.django_db
def test_preview_requires_authentication():
    """
    Step 5/5 preview should not be visible to anonymous users.
    If user is not logged in, return 401.
    """
    owner = User.objects.create_user(
        username="owner3", email="owner3@example.com", password="pass1234"
    )
    cat = RoomCategorie.objects.create(name="General")

    room = Room.objects.create(
        title="Auth required preview",
        description="A " + "very nice room " * 20,
        price_per_month=600,
        security_deposit=100,
        location="30 Test Street London SW1A 1AA",
        category=cat,
        property_owner=owner,
        status="draft",
    )

    client = APIClient()  # no authentication

    url = reverse("api:room-preview", kwargs={"pk": room.pk})
    response = client.get(url)

    assert response.status_code == 401


@pytest.mark.django_db
def test_preview_uses_legacy_room_image_when_no_roomimage(tmp_path, settings):
    """
    If there are no RoomImage rows, preview should fall back
    to the legacy Room.image field and still return one photo
    with status='legacy'.
    """
    settings.MEDIA_ROOT = tmp_path

    owner = User.objects.create_user(
        username="owner4", email="owner4@example.com", password="pass1234"
    )
    cat = RoomCategorie.objects.create(name="General")

    room = Room.objects.create(
        title="Legacy image preview",
        description="A " + "very nice room " * 20,
        price_per_month=700,
        security_deposit=250,
        location="40 Test Street London SW1A 1AA",
        category=cat,
        property_owner=owner,
        status="draft",
        image="room_images/legacy_photo.jpg",  # legacy ImageField
    )

    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("api:room-preview", kwargs={"pk": room.pk})
    response = client.get(url)

    assert response.status_code == 200

    data = response.json()
    photos = data.get("photos", [])

    assert len(photos) == 1
    assert photos[0]["status"] == "legacy"
    assert "legacy_photo.jpg" in photos[0]["url"]
