
# They prove:

# verified users can log in
# unverified users cannot
# login works with username or email
# tokens and expiry fields are returned
# lockout logic works




import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from propertylist_app.models import UserProfile

pytestmark = pytest.mark.django_db


def make_verified_user():
    user = get_user_model().objects.create_user(
        username="loginuser",
        email="loginuser@example.com",
        password="StrongPass1!",
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.save(update_fields=["email_verified"])
    return user


def make_unverified_user():
    user = get_user_model().objects.create_user(
        username="unverifieduser",
        email="unverifieduser@example.com",
        password="StrongPass1!",
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = False
    profile.save(update_fields=["email_verified"])
    return user


def test_login_with_email_returns_tokens(api_client):
    user = make_verified_user()
    url = reverse("api:auth-login")

    response = api_client.post(
        url,
        {"identifier": user.email, "password": "StrongPass1!"},
        format="json",
    )

    assert response.status_code == 200, response.json()
    body = response.json()

    assert body["ok"] is True
    assert "tokens" in body["data"]
    assert "access" in body["data"]["tokens"]
    assert "refresh" in body["data"]["tokens"]
    assert "access_expires_at" in body["data"]["tokens"]
    assert "refresh_expires_at" in body["data"]["tokens"]
    assert body["data"]["profile"]["email_verified"] is True


def test_login_with_username_returns_tokens(api_client):
    user = make_verified_user()
    url = reverse("api:auth-login")

    response = api_client.post(
        url,
        {"identifier": user.username, "password": "StrongPass1!"},
        format="json",
    )

    assert response.status_code == 200, response.json()


def test_login_rejects_unverified_user(api_client):
    user = make_unverified_user()
    url = reverse("api:auth-login")

    response = api_client.post(
        url,
        {"identifier": user.email, "password": "StrongPass1!"},
        format="json",
    )

    assert response.status_code == 403, response.json()


def test_login_wrong_password_returns_400(api_client):
    user = make_verified_user()
    url = reverse("api:auth-login")

    response = api_client.post(
        url,
        {"identifier": user.email, "password": "WrongPass1!"},
        format="json",
    )

    assert response.status_code == 400, response.json()


@override_settings(LOGIN_FAIL_LIMIT=3, LOGIN_LOCKOUT_SECONDS=300)
def test_login_locks_after_repeated_failures(api_client):
    user = make_verified_user()
    url = reverse("api:auth-login")

    for _ in range(3):
        response = api_client.post(
            url,
            {"identifier": user.email, "password": "WrongPass1!"},
            format="json",
        )
        assert response.status_code == 400

    response = api_client.post(
        url,
        {"identifier": user.email, "password": "WrongPass1!"},
        format="json",
    )

    assert response.status_code == 429, response.json()