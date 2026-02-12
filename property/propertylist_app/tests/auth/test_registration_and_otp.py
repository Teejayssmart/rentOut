import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile, EmailOTP


@pytest.fixture
def api():
    return APIClient()


# -----------------------------
# Helpers: always use URL reversing
# -----------------------------
def register_url():
    # v1 namespaced route from propertylist_app/api/urls.py
    return reverse("v1:auth-register")


def verify_otp_url():
    return reverse("v1:auth-verify-otp")


def resend_otp_url():
    return reverse("v1:auth-resend-otp")


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
    res = api.post(register_url(), _register_payload("landlord"), format="json")
    assert res.status_code == 201, getattr(res, "data", res.content)
    assert res.data.get("need_otp") is True

    User = get_user_model()
    u = User.objects.get(username="testuser")

    p = UserProfile.objects.get(user=u)
    assert p.role == "landlord"
    assert p.email_verified is False
    assert p.terms_accepted_at is not None
    assert p.terms_version == "v1.0"

    assert EmailOTP.objects.filter(user=u, used_at__isnull=True).exists()


@pytest.mark.django_db
def test_register_seeker_ok_sends_otp(api):
    data = _register_payload("seeker")
    data["username"] = "seekuser"
    data["email"] = "seek@example.com"

    res = api.post(register_url(), data, format="json")
    assert res.status_code == 201, getattr(res, "data", res.content)

    u = get_user_model().objects.get(username="seekuser")
    p = UserProfile.objects.get(user=u)
    assert p.role == "seeker"
    assert EmailOTP.objects.filter(user=u, used_at__isnull=True).exists()


@pytest.mark.django_db
def test_register_missing_terms_400(api):
    bad = _register_payload()
    bad["terms_accepted"] = False

    res = api.post(register_url(), bad, format="json")
    assert res.status_code == 400
    assert "terms_accepted" in res.data


@pytest.mark.django_db
def test_register_invalid_role_400(api):
    bad = _register_payload()
    bad["role"] = "owner"  # invalid

    res = api.post(register_url(), bad, format="json")
    assert res.status_code == 400


@pytest.mark.django_db
def test_register_duplicate_email_400(api):
    res1 = api.post(register_url(), _register_payload(), format="json")
    assert res1.status_code == 201, getattr(res1, "data", res1.content)

    dup = _register_payload()
    dup["username"] = "anotheruser"

    res2 = api.post(register_url(), dup, format="json")
    assert res2.status_code == 400


@pytest.mark.django_db
def test_register_duplicate_username_400(api):
    res1 = api.post(register_url(), _register_payload(), format="json")
    assert res1.status_code == 201, getattr(res1, "data", res1.content)

    dup = _register_payload()
    dup["email"] = "new@example.com"

    res2 = api.post(register_url(), dup, format="json")
    assert res2.status_code == 400


@pytest.mark.django_db
def test_verify_otp_ok_sets_email_verified(api):
    res = api.post(register_url(), _register_payload(), format="json")
    assert res.status_code == 201, getattr(res, "data", res.content)

    User = get_user_model()
    u = User.objects.get(username="testuser")

    # expire any active OTP so we can control the code
    EmailOTP.objects.filter(user=u, used_at__isnull=True).update(used_at=timezone.now())
    otp = EmailOTP.create_for(u, "123456", ttl_minutes=10)

    res2 = api.post(verify_otp_url(), {"user_id": u.id, "code": "123456"}, format="json")
    assert res2.status_code == 200, getattr(res2, "data", res2.content)

    p = UserProfile.objects.get(user=u)
    assert p.email_verified is True
    assert p.email_verified_at is not None

    otp.refresh_from_db()
    assert otp.used_at is not None


@pytest.mark.django_db
def test_verify_otp_wrong_code_400_and_attempts_increment(api):
    res = api.post(register_url(), _register_payload(), format="json")
    assert res.status_code == 201, getattr(res, "data", res.content)

    u = get_user_model().objects.get(username="testuser")

    EmailOTP.objects.filter(user=u, used_at__isnull=True).update(used_at=timezone.now())
    otp = EmailOTP.create_for(u, "123456", ttl_minutes=10)

    res2 = api.post(verify_otp_url(), {"user_id": u.id, "code": "000000"}, format="json")
    assert res2.status_code == 400

    otp.refresh_from_db()
    assert otp.attempts == 1


@pytest.mark.django_db
def test_verify_otp_expired_400(api):
    res = api.post(register_url(), _register_payload(), format="json")
    assert res.status_code == 201, getattr(res, "data", res.content)

    u = get_user_model().objects.get(username="testuser")

    # create an expired OTP
    EmailOTP.create_for(u, "123456", ttl_minutes=0)

    res2 = api.post(verify_otp_url(), {"user_id": u.id, "code": "123456"}, format="json")
    assert res2.status_code == 400
    assert "expired" in str(res2.data).lower()


@pytest.mark.django_db
def test_resend_otp_204_and_old_invalidated(api):
    res = api.post(register_url(), _register_payload(), format="json")
    assert res.status_code == 201, getattr(res, "data", res.content)

    u = get_user_model().objects.get(username="testuser")

    old_active = EmailOTP.objects.filter(user=u, used_at__isnull=True).order_by("-created_at").first()
    assert old_active is not None

    res2 = api.post(resend_otp_url(), {"user_id": u.id}, format="json")
    assert res2.status_code == 204

    old_active.refresh_from_db()
    assert old_active.used_at is not None
    assert EmailOTP.objects.filter(user=u, used_at__isnull=True).exists()
