import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def test_apple_register_requires_identity_token():
    client = APIClient()
    response = client.post("/api/v1/auth/register/apple/", {}, format="json")

    assert response.status_code == 400
    assert response.data["ok"] is False
    assert response.data["message"] == "Missing identity_token"
    assert response.data["data"] is None


def test_apple_register_rejects_invalid_token(monkeypatch):
    client = APIClient()

    def fake_verify(token):
        raise ValueError("Invalid Apple identity token")

    monkeypatch.setattr(
        "propertylist_app.api.views._verify_apple_identity_token",
        fake_verify,
    )

    response = client.post(
        "/api/v1/auth/register/apple/",
        {"identity_token": "fake"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["ok"] is False
    assert response.data["message"] == "Invalid Apple identity token"
    assert response.data["data"] is None


def test_apple_register_accepts_valid_token(monkeypatch):
    client = APIClient()

    def fake_verify(token):
        return {
            "email": "appleuser@example.com",
            "email_verified": True,
            "sub": "apple-sub-123",
            "iss": "https://appleid.apple.com",
            "aud": "com.example.web",
        }

    monkeypatch.setattr(
        "propertylist_app.api.views._verify_apple_identity_token",
        fake_verify,
    )

    response = client.post(
        "/api/v1/auth/register/apple/",
        {"identity_token": "valid-apple-token"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["ok"] is True
    assert response.data["message"] == "Login successful"
    assert "refresh" in response.data["data"]
    assert "access" in response.data["data"]

    user = get_user_model().objects.get(email="appleuser@example.com")
    assert user.username == "appleuser"