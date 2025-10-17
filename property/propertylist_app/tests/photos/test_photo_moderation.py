import io
import pytest
from PIL import Image
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from propertylist_app.models import Room, RoomCategorie, RoomImage

User = get_user_model()

def _make_image_file(name="test.jpg", size=(50, 50), fmt="JPEG"):
    buf = io.BytesIO()
    img = Image.new("RGB", size, "white")
    img.save(buf, fmt)
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/jpeg")

@pytest.mark.django_db
def test_photo_upload_is_pending_and_hidden_until_approved():
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="R1", description="x", price_per_month=500, location="SW1A 1AA",
        category=cat, property_owner=owner, property_type="flat"
    )

    client = APIClient()
    client.force_authenticate(owner)

    url = reverse("v1:room-photo-upload", kwargs={"pk": room.id})

    # Upload → should be created as pending
    img = _make_image_file()
    r = client.post(url, {"image": img}, format="multipart")
    assert r.status_code == 201, r.data
    photo_id = r.data["id"]

    photo = RoomImage.objects.get(id=photo_id)
    assert photo.status == "pending"

    # Public list (owner-auth ok; endpoint returns only approved)
    r2 = client.get(url)
    assert r2.status_code == 200
    assert r2.data == []  # nothing visible yet

    # Approve it (simulate admin action by flipping status)
    photo.status = "approved"
    photo.save(update_fields=["status"])

    # Now visible
    r3 = client.get(url)
    assert r3.status_code == 200
    ids = [p["id"] for p in r3.data]
    assert photo_id in ids



@pytest.mark.django_db
def test_rejected_images_are_hidden():
    owner = User.objects.create_user(username="owner2", password="pass123", email="o2@example.com")
    cat = RoomCategorie.objects.create(name="Any2", active=True)
    room = Room.objects.create(
        title="R2", description="x", price_per_month=600, location="SW1A 2AA",
        category=cat, property_owner=owner, property_type="flat"
    )

    client = APIClient()
    client.force_authenticate(owner)

    url = reverse("v1:room-photo-upload", kwargs={"pk": room.id})

    img = _make_image_file(name="bad.jpg")
    r = client.post(url, {"image": img}, format="multipart")
    assert r.status_code == 201, r.data
    photo_id = r.data["id"]
    photo = RoomImage.objects.get(id=photo_id)

    # Reject it
    photo.status = "rejected"
    photo.save(update_fields=["status"])

    # Listing endpoint should not show rejected
    r2 = client.get(url)
    assert r2.status_code == 200
    ids = [p["id"] for p in r2.data]
    assert photo_id not in ids
