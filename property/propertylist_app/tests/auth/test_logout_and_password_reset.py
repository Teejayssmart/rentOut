import pytest
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_logout_happy_path_and_missing_refresh():
    """
    Real life: user logs out in the app.
    Your LogoutView requires:
      1) Authenticated user (via Authorization: Bearer <access>)
      2) A refresh token in the JSON body
    """
    # Create a user and login to get tokens
    u = User.objects.create_user(username="bob", email="b@example.com", password="pass12345")
    client = APIClient()

    # Login to get tokens
    url_login = reverse("v1:auth-login")
    r_login = client.post(url_login, {"username": "bob", "password": "pass12345"}, format="json")
    assert r_login.status_code == 200, r_login.data
    access = r_login.data["access"]
    refresh = r_login.data["refresh"]

    # Authenticate requests with the access token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    # Happy path logout (requires refresh in body)
    url_logout = reverse("v1:auth-logout")
    r_ok = client.post(url_logout, {"refresh": refresh}, format="json")
    assert r_ok.status_code == 200, r_ok.data
    assert r_ok.data.get("detail") == "Logged out."

    # Missing refresh -> 400, still authenticated via access token
    r_bad = client.post(url_logout, {}, format="json")
    assert r_bad.status_code == 400, r_bad.data


@pytest.mark.django_db
def test_password_reset_request_and_confirm_smoke():
    """
    Real life: user taps 'Forgot password' and then sets a new one.
    We just smoke-test the endpoints with your current mock behavior.
    """
    User.objects.create_user(username="carol", email="c@example.com", password="pass12345")
    client = APIClient()

    # Request reset
    url_req = reverse("v1:auth-password-reset")
    r1 = client.post(url_req, {"email": "c@example.com"}, format="json")
    assert r1.status_code == 200, r1.data

    # Confirm reset (token verification mocked in your view)
    url_cfm = reverse("v1:auth-password-reset-confirm")
    r2 = client.post(url_cfm, {"token": "dummy-token", "new_password": "newpass999"}, format="json")
    assert r2.status_code == 200, r2.data
    assert r2.data.get("detail") == "Password has been reset"
