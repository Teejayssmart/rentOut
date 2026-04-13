# They prove:

# OTP verify works
# email becomes verified
# used OTP is marked used
# wrong code increments attempts
# expired code fails
# resend replaces old OTP
# OTP remains hashed






import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from propertylist_app.models import EmailOTP, UserProfile

pytestmark = pytest.mark.django_db


def make_user():
    user = get_user_model().objects.create_user(
        username="otpuser",
        email="otpuser@example.com",
        password="StrongPass1!",
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def test_verify_email_otp_marks_profile_verified(api_client):
    user = make_user()
    otp = EmailOTP.create_for(user, "123456", ttl_minutes=10)

    url = reverse("api:auth-verify-otp")
    response = api_client.post(
        url,
        {"user_id": user.id, "code": "123456"},
        format="json",
    )

    assert response.status_code == 200, response.json()

    otp.refresh_from_db()
    user.profile.refresh_from_db()

    assert otp.used_at is not None
    assert user.profile.email_verified is True
    assert user.profile.email_verified_at is not None


def test_verify_email_otp_wrong_code_increments_attempts(api_client):
    user = make_user()
    otp = EmailOTP.create_for(user, "123456", ttl_minutes=10)

    url = reverse("api:auth-verify-otp")
    response = api_client.post(
        url,
        {"user_id": user.id, "code": "000000"},
        format="json",
    )

    assert response.status_code == 400, response.json()

    otp.refresh_from_db()
    assert otp.used_at is None
    assert otp.attempts == 1


def test_verify_email_otp_rejects_expired_code(api_client):
    user = make_user()
    otp = EmailOTP.create_for(user, "123456", ttl_minutes=0)
    otp.expires_at = timezone.now() - timezone.timedelta(minutes=1)
    otp.save(update_fields=["expires_at"])

    url = reverse("api:auth-verify-otp")
    response = api_client.post(
        url,
        {"user_id": user.id, "code": "123456"},
        format="json",
    )

    assert response.status_code == 400, response.json()


def test_resend_email_otp_invalidates_old_code_and_creates_new_one(api_client):
    user = make_user()
    old_otp = EmailOTP.create_for(user, "123456", ttl_minutes=10)

    url = reverse("api:auth-resend-otp")
    response = api_client.post(
        url,
        {"user_id": user.id, "confirm": True},
        format="json",
    )

    assert response.status_code == 200, response.json()

    old_otp.refresh_from_db()
    new_otps = EmailOTP.objects.filter(user=user, used_at__isnull=True).order_by("-created_at")

    assert old_otp.used_at is not None
    assert new_otps.exists()
    newest = new_otps.first()
    assert newest.id != old_otp.id
    assert len(newest.code) > 20  # hashed


def test_verify_email_otp_unknown_user_rejected(api_client):
    url = reverse("api:auth-verify-otp")
    response = api_client.post(
        url,
        {"user_id": 999999, "code": "123456"},
        format="json",
    )

    assert response.status_code == 400