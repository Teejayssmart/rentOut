import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

from propertylist_app.models import Room, RoomCategorie, RoomImage

from rest_framework.test import APIClient

User = get_user_model()


def _png(name="ok.png", size=100):
    return SimpleUploadedFile(
        name,
        b"\x89PNG\r\n\x1a\n" + b"\x00" * size,
        content_type="image/png",
    )


@pytest.mark.django_db
def test_room_photos_get_returns_only_approved():
    owner = User.objects.create_user(username="o", password="x")
    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="Room", description="..", price_per_month=700, location="M1 1AA",
        category=cat, property_owner=owner
    )

    # Seed images at different moderation states
    RoomImage.objects.create(room=room, image=_png("p1.png"), status="pending")
    RoomImage.objects.create(room=room, image=_png("r1.png"), status="rejected")
    approved = RoomImage.objects.create(room=room, image=_png("a1.png"), status="approved")

    url = reverse("v1:room-photo-upload", kwargs={"pk": room.pk})
    # GET returns only approved
    
    c = APIClient()
    r = c.get(url)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == approved.id
