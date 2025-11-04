import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


@pytest.fixture()
def api_client():
    return APIClient()


@pytest.mark.django_db
def test_refresh_token_returns_new_access(api_client, django_user_model):
    user = django_user_model.objects.create_user(username="bob", password="pass1234")

    login_url = reverse("v1:auth-login")
    resp = api_client.post(login_url, {"username": "bob", "password": "pass1234"}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    refresh_token = resp.data["refresh"]

    refresh_url = reverse("token_refresh")
    r = api_client.post(refresh_url, {"refresh": refresh_token}, format="json")
    assert r.status_code == status.HTTP_200_OK
    assert "access" in r.data
    assert r.data["access"] != resp.data["access"]


@pytest.mark.django_db
def test_refresh_token_invalid_or_expired_fails(api_client):
    refresh_url = reverse("token_refresh")
    resp = api_client.post(refresh_url, {"refresh": "invalidtoken"}, format="json")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
