import pytest
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import PhoneOTP, UserProfile


def phone_start_url() -> str:
    return "/api/auth/phone/start/"


def phone_verify_url() -> str:
    return "/api/auth/phone/verify/"


def make_user(email: str):
    User = get_user_model()
    username = email.split("@")[0]
    return User.objects.create_user(
        username=username,
        email=email,
        password="pass12345",
    )


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_phone_start_requires_auth():
    user = make_user("phone_start_auth@example.com")

    anon = APIClient()
    res = anon.post(phone_start_url(), data={"phone": "07123456789"}, format="json")
    assert res.status_code in (401, 403)

    client = auth_client(user)
    res2 = client.post(phone_start_url(), data={"phone": "07123456789"}, format="json")
    assert res2.status_code == 200


@pytest.mark.django_db
def test_phone_start_rejects_missing_or_short_phone():
    user = make_user("phone_start_bad@example.com")
    client = auth_client(user)

    res = client.post(phone_start_url(), data={"phone": ""}, format="json")
    assert res.status_code == 400

    res2 = client.post(phone_start_url(), data={"phone": "123"}, format="json")
    assert res2.status_code == 400


@pytest.mark.django_db
def test_phone_start_creates_phone_otp():
    user = make_user("phone_start_creates@example.com")
    client = auth_client(user)

    res = client.post(phone_start_url(), data={"phone": "07123456789"}, format="json")
    assert res.status_code == 200

    otp = PhoneOTP.objects.filter(user=user, phone="07123456789").order_by("-created_at").first()
    assert otp is not None
    assert otp.used_at is None
    assert otp.expires_at > timezone.now()
    assert len(otp.code) == 6
    assert otp.code.isdigit()


@pytest.mark.django_db
def test_phone_verify_requires_auth():
    user = make_user("phone_verify_auth@example.com")

    anon = APIClient()
    res = anon.post(phone_verify_url(), data={"phone": "07123456789", "code": "123456"}, format="json")
    assert res.status_code in (401, 403)

    client = auth_client(user)
    # no OTP exists yet -> 400
    res2 = client.post(phone_verify_url(), data={"phone": "07123456789", "code": "123456"}, format="json")
    assert res2.status_code == 400


@pytest.mark.django_db
def test_phone_verify_rejects_wrong_code_and_tracks_attempts():
    user = make_user("phone_verify_wrong@example.com")
    client = auth_client(user)

    otp = PhoneOTP.objects.create(
        user=user,
        phone="07123456789",
        code="111111",
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    res = client.post(phone_verify_url(), data={"phone": "07123456789", "code": "222222"}, format="json")
    assert res.status_code == 400

    otp.refresh_from_db()
    assert otp.used_at is None
    assert otp.attempts == 1


@pytest.mark.django_db
def test_phone_verify_rejects_expired_otp():
    user = make_user("phone_verify_expired@example.com")
    client = auth_client(user)

    PhoneOTP.objects.create(
        user=user,
        phone="07123456789",
        code="123456",
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    res = client.post(phone_verify_url(), data={"phone": "07123456789", "code": "123456"}, format="json")
    assert res.status_code == 400


@pytest.mark.django_db
def test_phone_verify_success_marks_profile_verified():
    user = make_user("phone_verify_ok@example.com")
    client = auth_client(user)

    otp = PhoneOTP.objects.create(
        user=user,
        phone="07123456789",
        code="123456",
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    res = client.post(phone_verify_url(), data={"phone": "07123456789", "code": "123456"}, format="json")
    assert res.status_code == 200

    otp.refresh_from_db()
    assert otp.used_at is not None

    profile = UserProfile.objects.get(user=user)
    assert profile.phone == "07123456789"
    assert profile.phone_verified is True
    assert profile.phone_verified_at is not None
