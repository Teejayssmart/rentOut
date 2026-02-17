import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from django.utils import timezone

from propertylist_app.models import UserProfile, EmailOTP

API = "/api"

@pytest.fixture
def api():
    return APIClient()

@pytest.mark.django_db
def test_login_with_username_after_verify_ok(api):
    # create a verified user
    User = get_user_model()
    u = User.objects.create_user(username="mixuser", email="mix@example.com", password="Str0ng!Pass")
    p, _ = UserProfile.objects.get_or_create(user=u, defaults={"role": "seeker"})
    p.email_verified = True
    p.email_verified_at = timezone.now()
    p.save()

    res = api.post(f"{API}/auth/login/", {"identifier": "mixuser", "password": "Str0ng!Pass"}, format="json")
    assert res.status_code == 200, res.data
    assert "data" in res.data and res.data["ok"] is True
    assert "tokens" in res.data["data"]
    assert "access" in res.data["data"]["tokens"]
    assert "refresh" in res.data["data"]["tokens"]



@pytest.mark.django_db
def test_login_with_email_after_verify_ok(api):
    User = get_user_model()
    u = User.objects.create_user(username="mixuser", email="mix@example.com", password="Str0ng!Pass")
    p, _ = UserProfile.objects.get_or_create(user=u, defaults={"role": "landlord"})
    p.email_verified = True
    p.email_verified_at = timezone.now()
    p.save()

    res = api.post(f"{API}/auth/login/", {"identifier": "mix@example.com", "password": "Str0ng!Pass"}, format="json")
    assert res.status_code == 200, res.data
    assert "data" in res.data and res.data["ok"] is True
    assert "tokens" in res.data["data"]
    assert "access" in res.data["data"]["tokens"]
    assert "refresh" in res.data["data"]["tokens"]


@pytest.mark.django_db
def test_login_before_verify_returns_403(api):
    # register flow creates an unverified profile; we simulate that
    User = get_user_model()
    u = User.objects.create_user(username="waituser", email="wait@example.com", password="Str0ng!Pass")
    UserProfile.objects.get_or_create(user=u, defaults={"role": "seeker", "email_verified": False})

    res = api.post(f"{API}/auth/login/", {"identifier": "waituser", "password": "Str0ng!Pass"}, format="json")
    assert res.status_code == 403
    assert "verify" in str(res.data).lower()

@pytest.mark.django_db
def test_login_bad_credentials_400(api):
    res = api.post(f"{API}/auth/login/", {"identifier": "nope", "password": "wrong"}, format="json")
    # Could be 400 invalid creds or 429 if locked — we expect 400 here
    assert res.status_code in (400, 401)
