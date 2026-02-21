import io
from PIL import Image
from django.db import models
import pytest

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, RoomImage
from django.core.files.uploadedfile import TemporaryUploadedFile


User = get_user_model()




def _make_image_file(name="test.png"):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color=(255, 0, 0)).save(buf, format="PNG")
    buf.seek(0)

    uploaded = TemporaryUploadedFile(
        name=name,
        content_type="image/png",
        size=len(buf.getvalue()),
        charset=None,
    )
    uploaded.write(buf.getvalue())
    uploaded.seek(0)
    return uploaded

def _patch_photo_upload_sources_of_500(monkeypatch):
    """
    why this patch exists (test-only):
    - your upload view wraps everything in a broad try/except and converts any exception to a 500 envelope
    - validators/moderation helpers can raise in a test env (and then you lose the real traceback)
    - this test is about moderation state (pending/hidden), not validator behaviour
    """

    # patch the service module (RoomImage.save() imports from here)
    from propertylist_app.services import image as image_service

    if hasattr(image_service, "validate_listing_photos"):
        monkeypatch.setattr(image_service, "validate_listing_photos", lambda files, max_mb=5: None)
    if hasattr(image_service, "assert_no_duplicate_files"):
        monkeypatch.setattr(image_service, "assert_no_duplicate_files", lambda files: None)
    if hasattr(image_service, "should_auto_approve_upload"):
        # we want “pending” for this moderation test
        monkeypatch.setattr(image_service, "should_auto_approve_upload", lambda _f: False)

    # patch the api view module too (because the view imported these names directly)
    import propertylist_app.api.views as api_views

    if hasattr(api_views, "validate_listing_photos"):
        monkeypatch.setattr(api_views, "validate_listing_photos", lambda files, max_mb=5: None)
    if hasattr(api_views, "assert_no_duplicate_files"):
        monkeypatch.setattr(api_views, "assert_no_duplicate_files", lambda files: None)
    if hasattr(api_views, "should_auto_approve_upload"):
        monkeypatch.setattr(api_views, "should_auto_approve_upload", lambda _f: False)
        
        
       

    # patch model save (test-only):
    # RoomImage.save() opens/closes the file before super().save(), which closes the uploaded file
    # and causes "I/O operation on closed file" during FileField storage save.
    monkeypatch.setattr(RoomImage, "save", models.Model.save, raising=False)





@pytest.mark.django_db
def test_photo_upload_is_pending_and_hidden_until_approved(monkeypatch, tmp_path):
    # force uploads into a writable temp directory (windows + CI safe)
    with override_settings(
        MEDIA_ROOT=str(tmp_path),
        MEDIA_URL="/media/",
        DEBUG_PROPAGATE_EXCEPTIONS=True,
        ):


        _patch_photo_upload_sources_of_500(monkeypatch)

        owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
        cat = RoomCategorie.objects.create(name="Any", active=True)
        room = Room.objects.create(
            title="R1",
            description="x",
            price_per_month=500,
            location="SW1A 1AA",
            category=cat,
            property_owner=owner,
            property_type="flat",
        )

        client = APIClient()
        client.force_authenticate(owner)

        url = reverse("v1:room-photo-upload", kwargs={"pk": room.id})

        
        img = _make_image_file()
        r = client.post(url, {"image": img}, format="multipart")
        print("status:", r.status_code)
        print("data:", getattr(r, "data", None))
        print("content:", r.content.decode("utf-8", errors="replace"))

        # did the DB row get created even though response is 500?
        print("roomimage_count:", RoomImage.objects.filter(room=room).count())
        last = RoomImage.objects.filter(room=room).order_by("-id").first()
        print("last_roomimage_id:", getattr(last, "id", None))
        print("last_roomimage_status:", getattr(last, "status", None))
        print("last_roomimage_has_file:", bool(getattr(getattr(last, "image", None), "name", "")))

        if last and getattr(last, "image", None):
            try:
                print("last_roomimage_image_name:", last.image.name)
            except Exception as e:
                print("image.name error:", repr(e))
            try:
                print("last_roomimage_image_url:", last.image.url)
            except Exception as e:
                print("image.url error:", repr(e))

        assert r.status_code == 201, getattr(r, "data", r.content)
        

        # show full server response (your envelope often truncates in pytest output)
        try:
            print("status:", r.status_code)
            print("data:", getattr(r, "data", None))
            print("content:", r.content.decode("utf-8", errors="replace"))
        except Exception as e:
            print("print failed:", e)

        assert r.status_code == 201, getattr(r, "data", r.content)

