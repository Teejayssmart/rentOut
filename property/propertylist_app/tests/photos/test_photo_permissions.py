import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, RoomImage


from django.urls import reverse

User = get_user_model()

def _png(name="ok.png", size=120):
    return SimpleUploadedFile(
        name,
        b"\x89PNG\r\n\x1a\n" + b"\x00" * size,
        content_type="image/png",
    )

@pytest.mark.django_db
def test_only_owner_can_upload_room_photo():
    owner = User.objects.create_user(username="o", password="x")
    other = User.objects.create_user(username="u", password="x")
    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="Room", description="..", price_per_month=700, location="M1 1AA",
        category=cat, property_owner=owner
    )

    url = reverse("v1:room-photo-upload", kwargs={"pk": room.pk})

    c = APIClient()

    # Not authenticated → 401
    r0 = c.post(url, data={"image": _png()}, format="multipart")
    assert r0.status_code in (401, 403)

    # Authenticated as non-owner → 403
    c.force_authenticate(user=other)
    r = c.post(url, data={"image": _png()}, format="multipart")
    assert r.status_code == 403

    # Owner → 201 and status=pending
    c.force_authenticate(user=owner)
    r2 = c.post(url, data={"image": _png()}, format="multipart")
    assert r2.status_code == 201, r2.data
    assert r2.data["status"] == "pending"
    assert RoomImage.objects.filter(room=room).count() == 1



@pytest.mark.django_db
def test_only_owner_can_delete_room_photo():
    owner = User.objects.create_user(username="o", password="x")
    other = User.objects.create_user(username="u", password="x")
    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="Room", description="..", price_per_month=700, location="M1 1AA",
        category=cat, property_owner=owner
    )
    from propertylist_app.models import RoomImage
    img = RoomImage.objects.create(room=room, image=_png("del.png"), status="pending")

    url = reverse("v1:room-photo-delete", kwargs={"pk": room.pk, "photo_id": img.pk})
    c = APIClient()

    # Non-owner → 403
    c.force_authenticate(user=other)
    r1 = c.delete(url)
    assert r1.status_code == 403

    # Owner → 204 and record removed
    c.force_authenticate(user=owner)
    r2 = c.delete(url)
    assert r2.status_code == 204
    assert not RoomImage.objects.filter(pk=img.pk).exists()
