import base64
import os
import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, RoomImage

User = get_user_model()


# 1x1 transparent PNG (valid image) – base64-encoded
_TINY_PNG_B64 = (
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)
def tiny_png_bytes() -> bytes:
    return base64.b64decode(_TINY_PNG_B64)


def big_png_bytes(size_mb: int = 6) -> bytes:
    """Start with a valid PNG and pad to exceed N MB so Pillow stays happy but size is large."""
    core = bytearray(tiny_png_bytes())
    pad = (size_mb * 1024 * 1024) - len(core)
    if pad > 0:
        core.extend(b"\0" * pad)
    return bytes(core)


@pytest.mark.django_db
def test_avatar_upload_rejects_oversize():
    """
    /api/v1/users/me/profile/avatar/ must reject files > 5MB (validate_avatar_image).
    """
    user = User.objects.create_user(username="u", password="pass123", email="u@example.com")
    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("v1:user-avatar-upload")

    upload = SimpleUploadedFile("big.png", big_png_bytes(6), content_type="image/png")

    resp = client.post(url, {"avatar": upload}, format="multipart")
    assert resp.status_code == 400, resp.data
    # error message may vary depending on handler, check generic text
    body = str(resp.data)
    assert "too large" in body.lower() or "max 5mb" in body.lower()


@pytest.mark.django_db
def test_avatar_upload_rejects_bad_mime():
    """
    /api/v1/users/me/profile/avatar/ must reject non-image content types.
    """
    user = User.objects.create_user(username="u2", password="pass123", email="u2@example.com")
    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("v1:user-avatar-upload")

    bad = SimpleUploadedFile("not-image.txt", b"hello world", content_type="text/plain")
    resp = client.post(url, {"avatar": bad}, format="multipart")
    assert resp.status_code == 400, resp.data
    assert "unsupported image type" in str(resp.data).lower()


@pytest.mark.django_db
def test_avatar_upload_accepts_valid_image_and_sets_profile_avatar_url(settings, tmp_path):
    """
    /api/v1/users/me/profile/avatar/ accepts a valid PNG and returns {"avatar": <url|None>}.
    """
    settings.MEDIA_ROOT = str(tmp_path / "media")

    user = User.objects.create_user(username="u3", password="pass123", email="u3@example.com")
    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("v1:user-avatar-upload")

    png = SimpleUploadedFile("ok.png", tiny_png_bytes(), content_type="image/png")
    resp = client.post(url, {"avatar": png}, format="multipart")
    assert resp.status_code == 200, resp.data
    assert "avatar" in resp.data
    assert isinstance(resp.data["avatar"], (str, type(None)))


@pytest.mark.django_db
def test_room_photo_upload_happy_path_creates_pending_image_record(settings, tmp_path):
    """
    Owner uploads a valid room photo -> 201 + RoomImage created with status 'pending'.
    """
    settings.MEDIA_ROOT = str(tmp_path / "media")

    owner = User.objects.create_user(username="landlord", password="pass123", email="l@example.com")
    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="Nice Room",
        description="desc",
        price_per_month=800,
        location="London SW1A 1AA",
        category=cat,
        property_owner=owner,
    )

    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("v1:room-photo-upload", kwargs={"pk": room.pk})

    img = SimpleUploadedFile("room1.png", tiny_png_bytes(), content_type="image/png")
    resp = client.post(url, {"image": img}, format="multipart")
    assert resp.status_code == 201, resp.data

    photos = RoomImage.objects.filter(room=room)
    assert photos.count() == 1
    photo = photos.first()
    assert photo.status == "pending"
    assert photo.image and os.path.exists(photo.image.path)
