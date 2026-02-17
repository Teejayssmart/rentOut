import pytest
from django.contrib.auth import get_user_model
from propertylist_app.models import UserProfile

API_LOGIN_URL = "/api/auth/login/"
API_REFRESH_URL = "/api/auth/token/refresh/"


@pytest.mark.django_db
def test_token_refresh_returns_consistent_success_envelope(api_client):
    User = get_user_model()

    user = User.objects.create_user(
        username="refreshuser",
        email="refreshuser@example.com",
        password="Str0ng!Pass123",
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.save()

    login = api_client.post(
        API_LOGIN_URL,
        {"identifier": "refreshuser", "password": "Str0ng!Pass123"},
        format="json",
    )
    assert login.status_code == 200

    refresh_token = login.data["data"]["tokens"]["refresh"]

    res = api_client.post(
        API_REFRESH_URL,
        {"refresh": refresh_token},
        format="json",
    )

    assert res.status_code == 200
    assert res.data["ok"] is True

    data = res.data["data"]
    assert "access" in data
    assert "access_expires_at" in data
    assert "refresh_expires_at" in data


@pytest.mark.django_db
def test_token_refresh_invalid_refresh_returns_400(api_client):
    res = api_client.post(
        API_REFRESH_URL,
        {"refresh": "not-a-real-token"},
        format="json",
    )
    assert res.status_code == 400
