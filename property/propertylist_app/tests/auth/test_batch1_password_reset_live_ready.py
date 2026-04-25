


# They prove:

# reset request works
# no email enumeration leak
# reset OTP is hashed
# correct token changes password
# wrong token increments attempts









import pytest
from django.contrib.auth import authenticate, get_user_model
from django.urls import reverse

from propertylist_app.models import EmailOTP

pytestmark = pytest.mark.django_db


def make_user():
    return get_user_model().objects.create_user(
        username="resetuser",
        email="resetuser@example.com",
        password="OldPass1!",
    )


def test_password_reset_request_creates_hashed_otp(api_client):
    user = make_user()
    url = reverse("api:auth-password-reset")

    response = api_client.post(url, {"email": user.email}, format="json")

    assert response.status_code == 200, response.json()

    otp = EmailOTP.objects.filter(
        user=user,
        purpose=EmailOTP.PURPOSE_PASSWORD_RESET,
        used_at__isnull=True,
    ).latest("created_at")

    assert len(otp.code) > 20


def test_password_reset_request_nonexistent_email_is_generic(api_client):
    url = reverse("api:auth-password-reset")

    response = api_client.post(url, {"email": "nobody@example.com"}, format="json")

    assert response.status_code == 200, response.json()


def test_password_reset_confirm_changes_password(api_client):
    user = make_user()
    EmailOTP.create_for(
        user,
        "123456",
        ttl_minutes=10,
        purpose=EmailOTP.PURPOSE_PASSWORD_RESET,
    )

    url = reverse("api:auth-password-reset-confirm")
    response = api_client.post(
        url,
        {
            "email": user.email,
            "token": "123456",
            "new_password": "NewPass1!",
            "confirm_password": "NewPass1!",
        },
        format="json",
    )

    assert response.status_code == 200, response.json()

    user.refresh_from_db()
    assert authenticate(username=user.username, password="OldPass1!") is None
    assert authenticate(username=user.username, password="NewPass1!") is not None


def test_password_reset_confirm_wrong_token_increments_attempts(api_client):
    user = make_user()
    otp = EmailOTP.create_for(
        user,
        "123456",
        ttl_minutes=10,
        purpose=EmailOTP.PURPOSE_PASSWORD_RESET,
    )

    url = reverse("api:auth-password-reset-confirm")
    response = api_client.post(
        url,
        {
            "email": user.email,
            "token": "000000",
            "new_password": "NewPass1!",
            "confirm_password": "NewPass1!",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()

    otp.refresh_from_db()
    assert otp.attempts == 1
    assert otp.used_at is None