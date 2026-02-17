import pytest
from django.contrib.auth import get_user_model
from propertylist_app.models import UserProfile

API_LOGIN_URL = "/api/auth/login/"


@pytest.mark.django_db
def test_login_returns_consistent_success_envelope_with_expiry_and_profile(api_client):
    User = get_user_model()

    user = User.objects.create_user(
        username="loginshapeuser",
        email="loginshapeuser@example.com",
        password="Str0ng!Pass123",
    )

    # LoginView blocks if profile missing or email not verified
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.role = getattr(profile, "role", None) or "seeker"
    profile.save()

    res = api_client.post(
        API_LOGIN_URL,
        {"identifier": "loginshapeuser", "password": "Str0ng!Pass123"},
        format="json",
    )

    assert res.status_code == 200
    assert res.data["ok"] is True

    data = res.data["data"]
    assert "tokens" in data
    assert "user" in data
    assert "profile" in data

    tokens = data["tokens"]
    assert "access" in tokens
    assert "refresh" in tokens
    assert "access_expires_at" in tokens
    assert "refresh_expires_at" in tokens

    user_block = data["user"]
    assert "id" in user_block
    assert "username" in user_block
    assert "email" in user_block

    profile_block = data["profile"]
    assert "user" in profile_block
