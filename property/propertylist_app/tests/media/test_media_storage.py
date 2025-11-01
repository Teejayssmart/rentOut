# property/propertylist_app/tests/media/test_media_storage.py
import io
import pytest
from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.conf import settings

from propertylist_app.validators.images import validate_avatar_image, validate_listing_photos

from propertylist_app.services.image import generate_thumbnails_and_return_paths
from propertylist_app.services.urls import signed_media_url


@pytest.mark.django_db
class TestMediaAndStorage:

    def make_image(self, fmt="JPEG", size=(100, 100), color=(255, 0, 0), name="test.jpg"):
        """Utility: create an in-memory image."""
        img = Image.new("RGB", size, color)
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        buf.seek(0)
        return SimpleUploadedFile(name, buf.read(), content_type=f"image/{fmt.lower()}")

    # ----------------------------------------------------------------------
    #  1. IMAGE CONSTRAINTS
    # ----------------------------------------------------------------------
    def test_avatar_image_validation_rejects_large_file(self):
        """Avatar validator should reject files > 5MB."""
        big_file = SimpleUploadedFile("big.jpg", b"x" * (6 * 1024 * 1024), content_type="image/jpeg")
        with pytest.raises(ValidationError):
            validate_avatar_image(big_file)

    def test_avatar_image_validation_accepts_small_jpeg(self):
        """Avatar validator should accept small JPEG file."""
        img = self.make_image(fmt="JPEG", size=(200, 200))
        result = validate_avatar_image(img)
        assert result == img

    def test_listing_photos_reject_unsupported_format(self):
        """Listing photo validator should reject .gif or unsupported formats."""
        bad_file = SimpleUploadedFile("bad.gif", b"x" * 1024, content_type="image/gif")
        with pytest.raises(ValidationError):
            validate_listing_photos([bad_file])

    # ----------------------------------------------------------------------
    #  2. THUMBNAIL GENERATION
    # ----------------------------------------------------------------------
    def test_generate_thumbnails_creates_two_files(self, tmp_path):
        """Thumbnails should be generated at 640px and 1280px."""
        img = self.make_image(fmt="JPEG", size=(1600, 1200))
        base_dir = str(tmp_path)
        out = generate_thumbnails_and_return_paths(img, base_dir, "thumbtest")
        assert isinstance(out, dict)
        assert "sm" in out and "md" in out
        for k, path in out.items():
            assert path.endswith(".webp")
            assert default_storage.exists(path)

    # ----------------------------------------------------------------------
    #  3. STORAGE BACKEND CHECK
    # ----------------------------------------------------------------------
    def test_storage_backend_is_local_or_s3(self):
        """Ensure the active backend is local (dev) or S3 (prod)."""
        storage_backend = default_storage.__class__.__name__.lower()
        assert "storage" in storage_backend  # sanity
        if getattr(settings, "USE_S3", False):
            assert "s3" in storage_backend
        else:
            assert "file" in storage_backend or "locmem" in storage_backend

    # ----------------------------------------------------------------------
    #  4. SIGNED URL POLICY
    # ----------------------------------------------------------------------
    def test_signed_media_url_returns_valid_url(self, tmp_path):
        """Signed media URL should produce a valid link (S3 or local)."""
        # Create a dummy file in storage
        f = tmp_path / "avatar_test.jpg"
        f.write_bytes(b"abc")
        rel_path = f.name
        # Save it to storage so URL works
        default_storage.save(rel_path, open(f, "rb"))
        url = signed_media_url(rel_path)
        assert isinstance(url, str)
        assert url.startswith("http") or url.startswith("/media/")
