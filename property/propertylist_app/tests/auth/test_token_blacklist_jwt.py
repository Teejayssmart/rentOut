import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

@pytest.fixture()
def api_client():
    return APIClient()

@pytest.mark.django_db
def test_logout_blacklists_refresh_token_cannot_refresh_anymore(api_client, django_user_model):
    # create user
    user = django_user_model.objects.create_user(username="bob", password="pass1234")

    login_url = reverse("v1:auth-login")
    logout_url = reverse("v1:auth-logout")
    refresh_url = reverse("token_refresh")

    # login → get tokens
    resp = api_client.post(login_url, {"username": "bob", "password": "pass1234"}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    refresh = resp.data["refresh"]
    access = resp.data["access"]

    # logout with access token (required by IsAuthenticated)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    out = api_client.post(logout_url, {"refresh": refresh}, format="json")
    assert out.status_code == status.HTTP_200_OK

    # trying to refresh with the same (now blacklisted) refresh token should fail
    api_client.credentials()  # no auth needed for refresh endpoint
    bad = api_client.post(refresh_url, {"refresh": refresh}, format="json")
    assert bad.status_code == status.HTTP_401_UNAUTHORIZED
    # be tolerant to payload variations across simplejwt versions
    assert ("code" in bad.data and bad.data["code"] == "token_not_valid") or "blacklist" in str(bad.data).lower()

@pytest.mark.django_db
def test_blacklisted_refresh_token_stays_blacklisted_on_reuse(api_client, django_user_model):
    user = django_user_model.objects.create_user(username="kate", password="pass1234")

    login_url = reverse("v1:auth-login")
    logout_url = reverse("v1:auth-logout")
    refresh_url = reverse("token_refresh")

    resp = api_client.post(login_url, {"username": "kate", "password": "pass1234"}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    refresh = resp.data["refresh"]
    access = resp.data["access"]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    out = api_client.post(logout_url, {"refresh": refresh}, format="json")
    assert out.status_code == status.HTTP_200_OK

    # first reuse → 401
    api_client.credentials()
    bad1 = api_client.post(refresh_url, {"refresh": refresh}, format="json")
    assert bad1.status_code == status.HTTP_401_UNAUTHORIZED

    # second reuse → still 401 (idempotent failure)
    bad2 = api_client.post(refresh_url, {"refresh": refresh}, format="json")
    assert bad2.status_code == status.HTTP_401_UNAUTHORIZED
