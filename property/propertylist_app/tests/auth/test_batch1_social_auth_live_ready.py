

# They prove:

# Google auth works
# Apple auth works
# profile verification is written correctly
# username collision logic works
# invalid provider tokens fail cleanly









import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from propertylist_app.models import UserProfile

pytestmark = pytest.mark.django_db


def test_google_register_creates_user_and_marks_profile_verified(api_client, monkeypatch):
    from propertylist_app.api.views import auth as auth_views

    def fake_verify_oauth2_token(token, request_obj, client_id):
        return {"email": "googleuser@example.com"}

    monkeypatch.setattr(auth_views.views_mod.id_token, "verify_oauth2_token", fake_verify_oauth2_token)

    url = reverse("api:auth-register-google")
    response = api_client.post(url, {"token": "fake-google-token"}, format="json")

    assert response.status_code == 200, response.json()

    user = get_user_model().objects.get(email="googleuser@example.com")
    profile = UserProfile.objects.get(user=user)

    assert profile.email_verified is True
    assert profile.email_verified_at is not None

    body = response.json()
    assert body["ok"] is True
    assert "access" in body["data"]
    assert "refresh" in body["data"]


def test_google_register_uses_unique_username_when_local_part_collides(api_client, monkeypatch):
    from propertylist_app.api.views import auth as auth_views

    get_user_model().objects.create_user(
        username="john",
        email="john1@example.com",
        password="StrongPass1!",
    )

    def fake_verify_oauth2_token(token, request_obj, client_id):
        return {"email": "john@example.com"}

    monkeypatch.setattr(auth_views.views_mod.id_token, "verify_oauth2_token", fake_verify_oauth2_token)

    url = reverse("api:auth-register-google")
    response = api_client.post(url, {"token": "fake-google-token"}, format="json")

    assert response.status_code == 200, response.json()

    user = get_user_model().objects.get(email="john@example.com")
    assert user.username != "john"
    assert user.username.startswith("john")


def test_apple_register_creates_user_and_marks_profile_verified(api_client, monkeypatch):
    from propertylist_app.api.views import auth as auth_views

    def fake_verify_apple_identity_token(token):
        return {"email": "appleuser@example.com"}

    monkeypatch.setattr(auth_views.views_mod, "_verify_apple_identity_token", fake_verify_apple_identity_token)

    url = reverse("api:auth-register-apple")
    response = api_client.post(url, {"identity_token": "fake-apple-token"}, format="json")

    assert response.status_code == 200, response.json()

    user = get_user_model().objects.get(email="appleuser@example.com")
    profile = UserProfile.objects.get(user=user)

    assert profile.email_verified is True
    assert profile.email_verified_at is not None

    body = response.json()
    assert body["ok"] is True
    assert "access" in body["data"]
    assert "refresh" in body["data"]


def test_google_register_invalid_token_returns_400(api_client, monkeypatch):
    from propertylist_app.api.views import auth as auth_views

    def fake_verify_oauth2_token(token, request_obj, client_id):
        raise Exception("bad token")

    monkeypatch.setattr(auth_views.views_mod.id_token, "verify_oauth2_token", fake_verify_oauth2_token)

    url = reverse("api:auth-register-google")
    response = api_client.post(url, {"token": "bad-token"}, format="json")

    assert response.status_code == 400, response.json()


def test_apple_register_invalid_token_returns_400(api_client, monkeypatch):
    from propertylist_app.api.views import auth as auth_views

    def fake_verify_apple_identity_token(token):
        raise ValueError("Invalid Apple identity token")

    monkeypatch.setattr(auth_views.views_mod, "_verify_apple_identity_token", fake_verify_apple_identity_token)

    url = reverse("api:auth-register-apple")
    response = api_client.post(url, {"identity_token": "bad-token"}, format="json")

    assert response.status_code == 400, response.json()