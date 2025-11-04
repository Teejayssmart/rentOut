import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from unittest.mock import patch

from rest_framework.test import APIClient
from rest_framework import status


@pytest.fixture()
def api_client():
    return APIClient()


@pytest.fixture()
@pytest.mark.django_db
def user():
    User = get_user_model()
    return User.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="pass1234",
    )


@pytest.mark.django_db
def test_login_success_returns_tokens(api_client, user):
    url = reverse("v1:auth-login")  # /api/v1/auth/login/
    resp = api_client.post(url, {"username": "alice", "password": "pass1234"}, format="json")
    assert resp.status_code == status.HTTP_200_OK, resp.data
    assert "access" in resp.data and "refresh" in resp.data
    assert isinstance(resp.data["access"], str) and resp.data["access"]
    assert isinstance(resp.data["refresh"], str) and resp.data["refresh"]


@pytest.mark.django_db
def test_login_invalid_credentials_no_tokens(api_client, user):
    url = reverse("v1:auth-login")
    resp = api_client.post(url, {"username": "alice", "password": "wrong"}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "access" not in resp.data and "refresh" not in resp.data
    assert resp.data.get("detail") == "Invalid credentials."


@pytest.mark.django_db
def test_access_protected_me_with_access_token(api_client, user):
    login_url = reverse("v1:auth-login")
    me_url = reverse("v1:user-me")

    login = api_client.post(login_url, {"username": "alice", "password": "pass1234"}, format="json")
    access = login.data["access"]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    me = api_client.get(me_url)
    assert me.status_code == status.HTTP_200_OK
    assert me.data.get("username") == "alice"


@pytest.mark.django_db
def test_logout_blacklists_refresh_token_and_refresh_fails(api_client, user):
    login_url = reverse("v1:auth-login")
    logout_url = reverse("v1:auth-logout")
    refresh_url = reverse("token_refresh")  # root urls, not namespaced

    login = api_client.post(login_url, {"username": "alice", "password": "pass1234"}, format="json")
    refresh = login.data["refresh"]
    access = login.data["access"]

    # must be authenticated to hit logout
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    out = api_client.post(logout_url, {"refresh": refresh}, format="json")
    assert out.status_code == status.HTTP_200_OK
    assert out.data.get("detail") == "Logged out."

    # refresh should now fail because it’s blacklisted
    bad = api_client.post(refresh_url, {"refresh": refresh}, format="json")
    assert bad.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_400_BAD_REQUEST)
    assert "detail" in bad.data or "code" in bad.data


@pytest.mark.django_db
def test_logout_without_refresh_is_400(api_client, user):
    logout_url = reverse("v1:auth-logout")

    login = api_client.post(reverse("v1:auth-login"), {"username": "alice", "password": "pass1234"}, format="json")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    resp = api_client.post(logout_url, {}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.data.get("detail") == "Refresh token required."


@pytest.mark.django_db
@patch("propertylist_app.api.views.verify_captcha", return_value=False)
def test_login_rejects_when_captcha_enabled(mock_verify, api_client, user, settings):
    settings.ENABLE_CAPTCHA = True

    url = reverse("v1:auth-login")
    resp = api_client.post(url, {"username": "alice", "password": "pass1234", "captcha_token": "x"}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.data.get("detail") == "CAPTCHA verification failed."
    mock_verify.assert_called_once()


@pytest.mark.django_db
@patch("propertylist_app.api.views.is_locked_out", return_value=True)
def test_login_locked_out_returns_429(mock_locked, api_client, user):
    url = reverse("v1:auth-login")
    resp = api_client.post(url, {"username": "alice", "password": "wrong"}, format="json")
    assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert resp.data.get("detail") == "Too many failed attempts. Try again later."
