# property/propertylist_app/tests/photos/test_room_photos.py
import io
import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from propertylist_app.models import RoomCategorie, Room, RoomImage

User = get_user_model()

# Ensure we have Pillow available; skip these tests if not installed
PIL_Image = pytest.importorskip("PIL.Image")


def make_valid_png_bytes() -> bytes:
    """
    Generate a tiny valid PNG with Pillow to satisfy DRF ImageField validation.
    """
    img = PIL_Image.new("RGBA", (2, 2), (255, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.django_db
def test_owner_can_upload_and_delete_room_photo():
    """
    Covers:
      - owner uploads a photo -> 201 & RoomImage created and linked to room
      - owner can delete a photo -> 204 (or 200) & RoomImage removed
    """
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Photos", active=True)
    room = Room.objects.create(
        title="Photo Room",
        description="desc",
        price_per_month=600,
        location="SW1A 1AA London",
        category=cat,
        property_owner=owner,
        property_type="flat",
    )

    client = APIClient()
    client.force_authenticate(user=owner)

    # Upload
    url_up = reverse("v1:room-photo-upload", kwargs={"pk": room.pk})
    upload = SimpleUploadedFile("pic.png", make_valid_png_bytes(), content_type="image/png")

    r1 = client.post(url_up, {"image": upload}, format="multipart")
    assert r1.status_code == 201, r1.data
    assert RoomImage.objects.filter(room=room).count() == 1
    photo_id = RoomImage.objects.filter(room=room).values_list("id", flat=True).first()

    # Delete
    url_del = reverse("v1:room-photo-delete", kwargs={"pk": room.pk, "photo_id": photo_id})
    r2 = client.delete(url_del)
    assert r2.status_code in (200, 204), r2.data
    assert RoomImage.objects.filter(room=room).count() == 0


@pytest.mark.django_db
def test_non_owner_cannot_upload_or_delete_room_photo():
    """
    Covers:
      - non-owner upload attempt -> 403
      - non-owner delete attempt -> 403
    """
    owner = User.objects.create_user(username="owner2", password="pass123", email="o2@example.com")
    intruder = User.objects.create_user(username="evil", password="pass123", email="e@example.com")
    cat = RoomCategorie.objects.create(name="Photos2", active=True)
    room = Room.objects.create(
        title="Not Yours",
        description="desc",
        price_per_month=700,
        location="EC1A 1BB London",
        category=cat,
        property_owner=owner,
        property_type="flat",
    )

    # Pre-create one photo owned by the room owner (so we can test DELETE perms)
    # We can create a RoomImage without an actual file path for permission check focus
    RoomImage.objects.create(room=room)

    c_bad = APIClient()
    c_bad.force_authenticate(user=intruder)

    # Upload attempt (with valid PNG so permission check triggers before validation)
    url_up = reverse("v1:room-photo-upload", kwargs={"pk": room.pk})
    upload = SimpleUploadedFile("hack.png", make_valid_png_bytes(), content_type="image/png")
    r1 = c_bad.post(url_up, {"image": upload}, format="multipart")
    assert r1.status_code in (401, 403), r1.data

    # Delete attempt
    photo_id = RoomImage.objects.filter(room=room).values_list("id", flat=True).first()
    url_del = reverse("v1:room-photo-delete", kwargs={"pk": room.pk, "photo_id": photo_id})
    r2 = c_bad.delete(url_del)
    assert r2.status_code in (401, 403), r2.data

    # Ensure nothing changed
    assert RoomImage.objects.filter(room=room).count() == 1
