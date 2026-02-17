import pytest
from django.contrib.auth import get_user_model
from propertylist_app.models import UserProfile

API_LOGIN_URL = "/api/auth/login/"
API_LOGOUT_URL = "/api/auth/logout/"
API_REFRESH_URL = "/api/auth/token/refresh/"


@pytest.mark.django_db
def test_logout_blacklists_refresh_and_returns_success_envelope(api_client):
    User = get_user_model()

    user = User.objects.create_user(
        username="logoutuser",
        email="logoutuser@example.com",
        password="Str0ng!Pass123",
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.save()

    login = api_client.post(
        API_LOGIN_URL,
        {"identifier": "logoutuser", "password": "Str0ng!Pass123"},
        format="json",
    )
    assert login.status_code == 200

    access = login.data["data"]["tokens"]["access"]
    refresh = login.data["data"]["tokens"]["refresh"]

    # Must be authenticated to logout
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    logout = api_client.post(API_LOGOUT_URL, {"refresh": refresh}, format="json")
    assert logout.status_code == 200
    assert logout.data["ok"] is True
    assert logout.data["data"]["detail"] == "Logged out."

    # Refresh token should now be invalid (blacklisted)
    api_client.credentials()  # refresh endpoint is AllowAny
    refreshed = api_client.post(API_REFRESH_URL, {"refresh": refresh}, format="json")
    assert refreshed.status_code == 400


@pytest.mark.django_db
def test_logout_missing_refresh_returns_400(api_client):
    User = get_user_model()

    user = User.objects.create_user(
        username="logoutmissing",
        email="logoutmissing@example.com",
        password="Str0ng!Pass123",
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.save()

    login = api_client.post(
        API_LOGIN_URL,
        {"identifier": "logoutmissing", "password": "Str0ng!Pass123"},
        format="json",
    )
    assert login.status_code == 200

    access = login.data["data"]["tokens"]["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    res = api_client.post(API_LOGOUT_URL, {}, format="json")
    assert res.status_code == 400


@pytest.mark.django_db
def test_logout_requires_authentication(api_client):
    res = api_client.post(API_LOGOUT_URL, {"refresh": "anything"}, format="json")
    assert res.status_code == 401
