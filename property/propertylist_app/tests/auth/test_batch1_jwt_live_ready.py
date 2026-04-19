import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from propertylist_app.models import UserProfile

pytestmark = pytest.mark.django_db


def make_verified_user():
    user = get_user_model().objects.create_user(
        username="jwtuser",
        email="jwtuser@example.com",
        password="StrongPass1!",
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.save(update_fields=["email_verified"])
    return user


def test_token_refresh_returns_access_token(api_client):
    user = make_verified_user()
    refresh = RefreshToken.for_user(user)

    url = reverse("api:auth-token-refresh")
    response = api_client.post(
        url,
        {"refresh": str(refresh)},
        format="json",
    )

    assert response.status_code == 200, response.json()
    body = response.json()

    assert body["ok"] is True
    assert "access" in body["data"]
    assert "access_expires_at" in body["data"]
    assert "refresh_expires_at" in body["data"]


def test_token_refresh_rejects_invalid_token(api_client):
    url = reverse("api:auth-token-refresh")
    response = api_client.post(
        url,
        {"refresh": "not-a-real-token"},
        format="json",
    )

    assert response.status_code in (400, 401), response.json()


def test_logout_blacklists_refresh_token(api_client):
    user = make_verified_user()
    refresh = RefreshToken.for_user(user)

    url = reverse("api:auth-logout")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {"refresh": str(refresh)},
        format="json",
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["detail"] == "Logged out."


def test_logout_then_refresh_fails(api_client):
    user = make_verified_user()
    refresh = RefreshToken.for_user(user)

    logout_url = reverse("api:auth-logout")
    refresh_url = reverse("api:auth-token-refresh")

    api_client.force_authenticate(user=user)
    logout_response = api_client.post(
        logout_url,
        {"refresh": str(refresh)},
        format="json",
    )
    assert logout_response.status_code == 200, logout_response.json()

    refresh_response = api_client.post(
        refresh_url,
        {"refresh": str(refresh)},
        format="json",
    )

    assert refresh_response.status_code in (400, 401), refresh_response.json()