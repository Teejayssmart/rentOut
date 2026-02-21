import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

from propertylist_app.models import Room, RoomCategorie, RoomImage

from rest_framework.test import APIClient
import io
from PIL import Image
from django.core.files.uploadedfile import TemporaryUploadedFile

from django.db import models
from django.test import override_settings


User = get_user_model()


def _png(name="ok.png"):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color=(255, 0, 0)).save(buf, format="PNG")
    data = buf.getvalue()

    f = TemporaryUploadedFile(
        name=name,
        content_type="image/png",
        size=len(data),
        charset=None,
    )
    f.write(data)
    f.seek(0)
    return f


@pytest.mark.django_db
@override_settings(MEDIA_URL="/media/")
def test_room_photos_get_returns_only_approved(monkeypatch):
    import propertylist_app.models as app_models
    monkeypatch.setattr(app_models.RoomImage, "save", models.Model.save, raising=False)
    owner = User.objects.create_user(username="o", password="x")
    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="Room", description="..", price_per_month=700, location="M1 1AA",
        category=cat, property_owner=owner
    )

    # Seed images at different moderation states
    app_models.RoomImage.objects.create(room=room, image=_png("p1.png"), status="pending")
    app_models.RoomImage.objects.create(room=room, image=_png("r1.png"), status="rejected")
    approved = app_models.RoomImage.objects.create(room=room, image=_png("a1.png"), status="approved")

    url = reverse("v1:room-photo-upload", kwargs={"pk": room.pk})
    # GET returns only approved
    
    c = APIClient()
    r = c.get(url)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == approved.id
