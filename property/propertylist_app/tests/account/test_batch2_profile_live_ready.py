import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from propertylist_app.models import UserProfile

pytestmark = pytest.mark.django_db

User = get_user_model()


def make_user():
    user = User.objects.create_user(
        username="batch2profile",
        email="batch2profile@example.com",
        password="StrongPass1!",
        first_name="Batch",
        last_name="Two",
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.role = "seeker"
    profile.save(update_fields=["email_verified", "role"])
    return user


def _payload_data(body):
    if isinstance(body, dict) and "data" in body and isinstance(body["data"], dict):
        return body["data"]
    return body


def test_user_profile_get_returns_profile(api_client):
    user = make_user()
    url = reverse("api:user-profile")

    api_client.force_authenticate(user=user)
    response = api_client.get(url, format="json")

    assert response.status_code == 200, response.json()
    body = response.json()
    data = _payload_data(body)

    assert data["user"] == user.id
    assert data["role"] == "seeker"
    assert data["email_verified"] is True


def test_user_profile_patch_updates_fields(api_client):
    user = make_user()
    url = reverse("api:user-profile")

    api_client.force_authenticate(user=user)
    response = api_client.patch(
        url,
        {
            "occupation": "Software engineer",
            "postcode": "sw1a1aa",
            "date_of_birth": "1990-01-01",
            "gender": "male",
            "about_you": "Friendly and tidy.",
            "role": "seeker",
            "role_detail": "current_flatmate",
            "address_manual": "10 Downing Street, London",
        },
        format="json",
    )

    assert response.status_code == 200, response.json()

    profile = UserProfile.objects.get(user=user)
    assert profile.occupation == "Software engineer"
    assert profile.postcode == "SW1A 1AA"
    assert str(profile.date_of_birth) == "1990-01-01"
    assert profile.gender == "male"
    assert profile.role == "seeker"
    assert profile.role_detail == "current_flatmate"
    assert profile.address_manual == "10 Downing Street, London"


def test_onboarding_complete_sets_flag(api_client):
    user = make_user()
    url = reverse("api:user-onboarding-complete")

    api_client.force_authenticate(user=user)
    response = api_client.post(url, {"confirm": True}, format="json")

    assert response.status_code == 200, response.json()
    body = response.json()

    assert body["ok"] is True
    assert body["data"]["onboarding_completed"] is True

    profile = UserProfile.objects.get(user=user)
    assert profile.onboarding_completed is True


def test_profile_page_returns_expected_shape(api_client):
    user = make_user()
    profile = UserProfile.objects.get(user=user)
    profile.occupation = "Designer"
    profile.postcode = "SW1A 1AA"
    profile.address_manual = "London"
    profile.about_you = "Hello"
    profile.save(update_fields=["occupation", "postcode", "address_manual", "about_you"])

    url = reverse("api:user-profile-page")

    api_client.force_authenticate(user=user)
    response = api_client.get(url, format="json")

    assert response.status_code == 200, response.json()
    body = response.json()

    assert body["ok"] is True
    data = body["data"]

    assert data["id"] == user.id
    assert data["email"] == user.email
    assert data["username"] == user.username
    assert data["role"] == profile.role
    assert data["occupation"] == "Designer"
    assert data["postcode"] == "SW1A 1AA"
    assert data["address_manual"] == "London"
    assert data["about_you"] == "Hello"
    assert "reviews_preview" in data