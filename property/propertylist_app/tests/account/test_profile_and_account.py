import io
import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile

User = get_user_model()


def _png_bytes():
    # Tiny 1x1 transparent PNG
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDAT\x08\xd7c``\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )



@pytest.mark.django_db
def test_avatar_upload_happy_path_and_missing_file():
    u = User.objects.create_user(username="ava", password="pass123", email="a@example.com")
    # Ensure profile exists
    UserProfile.objects.get_or_create(user=u)

    c = APIClient()
    c.force_authenticate(user=u)

    url = reverse("v1:user-avatar-upload")

    # Missing file -> 400
    r = c.post(url, data={}, format="multipart")
    assert r.status_code == 400
    assert "avatar" in str(r.data)

    # Valid PNG upload -> 200
    file = SimpleUploadedFile("tiny.png", _png_bytes(), content_type="image/png")
    r2 = c.post(url, data={"avatar": file}, format="multipart")
    assert r2.status_code == 200
    assert "avatar" in r2.data  # usually a URL or None depending on storage


@pytest.mark.django_db
def test_change_email_success_invalid_and_duplicate():
    u = User.objects.create_user(username="em", password="pass123", email="old@example.com")
    other = User.objects.create_user(username="other", password="pass123", email="taken@example.com")

    c = APIClient()
    c.force_authenticate(user=u)

    url = reverse("v1:user-change-email")

    # Invalid email -> 400
    r_bad = c.post(url, {"current_password": "pass123", "new_email": "not-an-email"})
    assert r_bad.status_code == 400

    # Duplicate email -> 400
    r_dup = c.post(url, {"current_password": "pass123", "new_email": "taken@example.com"})
    assert r_dup.status_code == 400

    # Happy path -> 200 and user email updated
    r_ok = c.post(url, {"current_password": "pass123", "new_email": "new@example.com"})
    assert r_ok.status_code == 200
    u.refresh_from_db()
    assert u.email == "new@example.com"


@pytest.mark.django_db
def test_change_password_success_mismatch_and_bad_current_and_login_with_new_password():
    u = User.objects.create_user(username="pwuser", password="pass123", email="pw@example.com")
    c = APIClient()
    c.force_authenticate(user=u)

    url = reverse("v1:user-change-password")

    # Mismatch -> 400
    r_mismatch = c.post(url, {
        "current_password": "pass123",
        "new_password": "Newpass12345!",
        "confirm_password": "Newpass12345!!",
    })
    assert r_mismatch.status_code == 400

    # Bad current -> 400
    r_badcur = c.post(url, {
        "current_password": "wrong",
        "new_password": "Newpass12345!",
        "confirm_password": "Newpass12345!",
    })
    assert r_badcur.status_code == 400

    # Happy path -> 200
    r_ok = c.post(url, {
        "current_password": "pass123",
        "new_password": "Newpass12345!",
        "confirm_password": "Newpass12345!",
    })
    assert r_ok.status_code == 200

   # Can log in with new password
    # Ensure profile exists + email is verified (your login flow can require this)
    UserProfile.objects.update_or_create(user=u, defaults={"email_verified": True})

    login_url = reverse("v1:auth-login")
    c2 = APIClient()
    r_login = c2.post(
        login_url,
        {"identifier": "pwuser", "password": "Newpass12345!"},
        format="json",
    )
    assert r_login.status_code == 200
    assert r_login.data.get("ok") is True
    assert "tokens" in r_login.data.get("data", {})
    assert "access" in r_login.data["data"]["tokens"]
    assert "refresh" in r_login.data["data"]["tokens"]




@pytest.mark.django_db
def test_deactivate_account_and_login_fails():
    u = User.objects.create_user(username="deact", password="pass123", email="d@example.com")
    c = APIClient()
    c.force_authenticate(user=u)

    url = reverse("v1:user-deactivate")
    r = c.post(url)
    assert r.status_code == 200

    # Try to log in again -> should fail
    
    login_url = reverse("v1:auth-login")
    c2 = APIClient()
    r_login = c2.post(login_url, {"username": "deact", "password": "pass123"}, format="json")
    # Depending on auth behavior for inactive users, it's typically 400 Invalid credentials
    assert r_login.status_code in (400, 401)
