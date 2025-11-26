import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile, EmailOTP

API = "/api"

@pytest.fixture
def api():
    return APIClient()

def _register_payload(role="landlord"):
    return {
        "username": "testuser",
        "email": "testuser@example.com",
        "password": "Str0ng!Pass",
        "password2": "Str0ng!Pass",
        "first_name": "Test",
        "last_name": "User",
        "role": role,  # landlord | seeker
        "terms_accepted": True,
        "terms_version": "v1.0",
        "marketing_consent": False,
    }

@pytest.mark.django_db
def test_register_landlord_ok_sends_otp(api):
    res = api.post(f"{API}/auth/register/", _register_payload("landlord"), format="json")
    assert res.status_code == 201, res.data
    assert res.data.get("need_otp") is True
    # user exists
    User = get_user_model()
    u = User.objects.get(username="testuser")
    # profile created with role + not verified yet
    p = UserProfile.objects.get(user=u)
    assert p.role == "landlord"
    assert p.email_verified is False
    assert p.terms_accepted_at is not None
    assert p.terms_version == "v1.0"
    # otp created
    assert EmailOTP.objects.filter(user=u, used_at__isnull=True).exists()

@pytest.mark.django_db
def test_register_seeker_ok_sends_otp(api):
    data = _register_payload("seeker")
    data["username"] = "seekuser"
    data["email"] = "seek@example.com"
    res = api.post(f"{API}/auth/register/", data, format="json")
    assert res.status_code == 201, res.data
    u = get_user_model().objects.get(username="seekuser")
    p = UserProfile.objects.get(user=u)
    assert p.role == "seeker"
    assert EmailOTP.objects.filter(user=u, used_at__isnull=True).exists()

@pytest.mark.django_db
def test_register_missing_terms_400(api):
    bad = _register_payload()
    bad["terms_accepted"] = False
    res = api.post(f"{API}/auth/register/", bad, format="json")
    assert res.status_code == 400
    assert "terms_accepted" in res.data

@pytest.mark.django_db
def test_register_invalid_role_400(api):
    bad = _register_payload()
    bad["role"] = "owner"  # invalid
    res = api.post(f"{API}/auth/register/", bad, format="json")
    assert res.status_code == 400

@pytest.mark.django_db
def test_register_duplicate_email_400(api):
    # first
    res1 = api.post(f"{API}/auth/register/", _register_payload(), format="json")
    assert res1.status_code == 201
    # second with same email
    dup = _register_payload()
    dup["username"] = "anotheruser"
    res2 = api.post(f"{API}/auth/register/", dup, format="json")
    # Either 400 field error or 201 with different handling, but we expect 400:
    assert res2.status_code == 400

@pytest.mark.django_db
def test_register_duplicate_username_400(api):
    res1 = api.post(f"{API}/auth/register/", _register_payload(), format="json")
    assert res1.status_code == 201
    dup = _register_payload()
    dup["email"] = "new@example.com"
    res2 = api.post(f"{API}/auth/register/", dup, format="json")
    assert res2.status_code == 400

@pytest.mark.django_db
def test_verify_otp_ok_sets_email_verified(api):
    # register
    res = api.post(f"{API}/auth/register/", _register_payload(), format="json")
    assert res.status_code == 201
    User = get_user_model()
    u = User.objects.get(username="testuser")
    # create a known OTP (since email contains the real one)
    EmailOTP.objects.filter(user=u, used_at__isnull=True).update(used_at=timezone.now())
    otp = EmailOTP.create_for(u, "123456", ttl_minutes=10)

    # verify
    res2 = api.post(f"{API}/auth/verify-otp/", {"user_id": u.id, "code": "123456"}, format="json")
    assert res2.status_code == 200, res2.data

    p = UserProfile.objects.get(user=u)
    assert p.email_verified is True
    assert p.email_verified_at is not None
    otp.refresh_from_db()
    assert otp.used_at is not None

@pytest.mark.django_db
def test_verify_otp_wrong_code_400_and_attempts_increment(api):
    res = api.post(f"{API}/auth/register/", _register_payload(), format="json")
    assert res.status_code == 201
    u = get_user_model().objects.get(username="testuser")
    EmailOTP.objects.filter(user=u, used_at__isnull=True).update(used_at=timezone.now())
    otp = EmailOTP.create_for(u, "123456", ttl_minutes=10)

    res2 = api.post(f"{API}/auth/verify-otp/", {"user_id": u.id, "code": "000000"}, format="json")
    assert res2.status_code == 400
    otp.refresh_from_db()
    assert otp.attempts == 1

@pytest.mark.django_db
def test_verify_otp_expired_400(api):
    res = api.post(f"{API}/auth/register/", _register_payload(), format="json")
    assert res.status_code == 201
    u = get_user_model().objects.get(username="testuser")
    # create an expired OTP
    expired = EmailOTP.create_for(u, "123456", ttl_minutes=0)
    res2 = api.post(f"{API}/auth/verify-otp/", {"user_id": u.id, "code": "123456"}, format="json")
    assert res2.status_code == 400
    assert "expired" in str(res2.data).lower()

@pytest.mark.django_db
def test_resend_otp_204_and_old_invalidated(api):
    res = api.post(f"{API}/auth/register/", _register_payload(), format="json")
    assert res.status_code == 201
    u = get_user_model().objects.get(username="testuser")

    # Capture current active OTP
    old_active = EmailOTP.objects.filter(user=u, used_at__isnull=True).order_by("-created_at").first()
    assert old_active is not None

    # Resend
    res2 = api.post(f"{API}/auth/resend-otp/", {"user_id": u.id}, format="json")
    assert res2.status_code == 204

    # Old should be used; new one should exist
    old_active.refresh_from_db()
    assert old_active.used_at is not None
    assert EmailOTP.objects.filter(user=u, used_at__isnull=True).exists()
