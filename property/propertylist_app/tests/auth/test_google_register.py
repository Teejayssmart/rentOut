import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def test_google_register_requires_token():
    client = APIClient()
    response = client.post("/api/v1/auth/register/google/", {}, format="json")

    assert response.status_code == 400
    assert response.data["ok"] is False
    assert response.data["message"] == "Missing token"
    assert response.data.get("data") is None


def test_google_register_rejects_invalid_token():
    client = APIClient()
    response = client.post(
        "/api/v1/auth/register/google/",
        {"token": "fake"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["ok"] is False
    assert response.data["message"] == "Invalid Google token"
    assert response.data.get("data") is None


def test_google_register_accepts_valid_token(monkeypatch):
    client = APIClient()

    def fake_verify_oauth2_token(token, request, audience):
        return {
            "email": "googleuser@example.com",
            "email_verified": True,
            "given_name": "Google",
            "family_name": "User",
            "sub": "google-sub-123",
            "iss": "https://accounts.google.com",
        }

    monkeypatch.setattr(
        "propertylist_app.api.views.id_token.verify_oauth2_token",
        fake_verify_oauth2_token,
    )

    response = client.post(
        "/api/v1/auth/register/google/",
        {"token": "valid-google-token"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["ok"] is True
    assert response.data["message"] == "Login successful"
    assert "refresh" in response.data["data"]
    assert "access" in response.data["data"]

    user = get_user_model().objects.get(email="googleuser@example.com")
    assert user.username == "googleuser"