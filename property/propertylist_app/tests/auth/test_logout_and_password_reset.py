import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile, EmailOTP


@pytest.mark.django_db
def test_logout_happy_path_and_missing_refresh():
    """
    Real life: user logs out in the app.
    Your LogoutView requires:
      1) Authenticated user (via Authorization: Bearer <access>)
      2) A refresh token in the JSON body
    """
    u = User.objects.create_user(username="bob", email="b@example.com", password="pass12345")
    UserProfile.objects.update_or_create(user=u, defaults={"email_verified": True})

    client = APIClient()

    # Login to get tokens (your login expects "identifier", not "username")
    url_login = reverse("v1:auth-login")
    r_login = client.post(url_login, {"identifier": "bob", "password": "pass12345"}, format="json")
    assert r_login.status_code == 200, r_login.data

    access = r_login.data["data"]["tokens"]["access"]
    refresh = r_login.data["data"]["tokens"]["refresh"]
    #refresh = r_login.data["refresh"]

    # Logout requires auth header
    url_logout = reverse("v1:auth-logout")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    # Missing refresh -> 400
    r_missing = client.post(url_logout, {}, format="json")
    assert r_missing.status_code == 400

    # Happy path -> 200/204 depending on implementation
    r_ok = client.post(url_logout, {"refresh": refresh}, format="json")
    assert r_ok.status_code in (200, 204), r_ok.data


@pytest.mark.django_db
def test_password_reset_request_and_confirm(monkeypatch):
    """
    Password reset flow:
      1) POST reset request (email) -> creates EmailOTP
      2) POST confirm (email + token + new_password) -> resets password
      3) Login with new password works
    """
    u = User.objects.create_user(username="resetuser", email="reset@example.com", password="pass12345")
    UserProfile.objects.update_or_create(user=u, defaults={"email_verified": True})

    client = APIClient()

    # Optional: prevent real email send in non-test environments
    def fake_send(*args, **kwargs):
        return True

    try:
        monkeypatch.setattr("django.core.mail.send_mail", fake_send)
    except Exception:
        pass

    # Step 1: request reset
    url_request = reverse("v1:auth-password-reset")
    r_req = client.post(url_request, {"email": "reset@example.com"}, format="json")
    assert r_req.status_code in (200, 204), r_req.data

    # Fetch the latest OTP created for this user (password reset)
    otp = (
        EmailOTP.objects
        .filter(user=u, used_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    assert otp is not None, "Expected an EmailOTP to be created for password reset."

    token = otp.code

    # Step 2: confirm reset
    url_confirm = reverse("v1:auth-password-reset-confirm")
    r_conf = client.post(
        url_confirm,
        {
            "email": "reset@example.com",
            "token": token,
            "new_password": "Newpass12345!",
            "confirm_password": "Newpass12345!",
        },
        format="json",
    )
    assert r_conf.status_code in (200, 204), r_conf.data


    # Step 3: login with new password works
    url_login = reverse("v1:auth-login")
    r_login = client.post(url_login, {"identifier": "resetuser", "password": "Newpass12345!"}, format="json")
    assert r_login.status_code == 200, r_login.data
    assert r_login.data.get("ok") is True
    assert "tokens" in r_login.data.get("data", {})
    assert "access" in r_login.data["data"]["tokens"]
    assert "refresh" in r_login.data["data"]["tokens"]

