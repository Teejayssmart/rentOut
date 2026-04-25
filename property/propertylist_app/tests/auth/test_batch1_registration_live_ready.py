

# They prove:

# user can register
# profile is created
# OTP is created
# OTP is hashed
# terms are enforced
# duplicate email/username are blocked
# weak password is blocked



import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from propertylist_app.models import UserProfile, EmailOTP

pytestmark = pytest.mark.django_db


def registration_payload(**overrides):
    data = {
        "username": "batch1user",
        "email": "batch1user@example.com",
        "password": "StrongPass1!",
        "password2": "StrongPass1!",
        "first_name": "Batch",
        "last_name": "One",
        "role": "seeker",
        "terms_accepted": True,
        "terms_version": "2026-04",
        "marketing_consent": False,
    }
    data.update(overrides)
    return data


def test_register_success_creates_user_profile_and_email_otp(api_client):
    url = reverse("api:auth-register")
    response = api_client.post(url, registration_payload(), format="json")

    assert response.status_code == 201, response.json()
    body = response.json()

    assert body["ok"] is True
    assert body["data"]["need_otp"] is True
    assert body["data"]["email"] == "batch1user@example.com"

    user = get_user_model().objects.get(email="batch1user@example.com")
    profile = UserProfile.objects.get(user=user)
    otp = EmailOTP.objects.filter(user=user, used_at__isnull=True).latest("created_at")

    assert profile.role == "seeker"
    assert profile.email_verified is False
    assert otp.code != "123456"
    assert len(otp.code) > 20  # hashed, not raw code


def test_register_requires_terms_accepted(api_client):
    url = reverse("api:auth-register")
    payload = registration_payload(terms_accepted=False)

    response = api_client.post(url, payload, format="json")

    assert response.status_code == 400
    body = response.json()
    assert "terms_accepted" in str(body)


def test_register_requires_terms_version(api_client):
    url = reverse("api:auth-register")
    payload = registration_payload(terms_version="")

    response = api_client.post(url, payload, format="json")

    assert response.status_code == 400
    body = response.json()
    assert "terms_version" in str(body)


def test_register_rejects_duplicate_email(api_client):
    User = get_user_model()
    User.objects.create_user(
        username="existinguser",
        email="batch1user@example.com",
        password="StrongPass1!",
    )

    url = reverse("api:auth-register")
    response = api_client.post(url, registration_payload(), format="json")

    assert response.status_code == 400


def test_register_rejects_duplicate_username(api_client):
    User = get_user_model()
    User.objects.create_user(
        username="batch1user",
        email="someoneelse@example.com",
        password="StrongPass1!",
    )

    url = reverse("api:auth-register")
    response = api_client.post(url, registration_payload(), format="json")

    assert response.status_code == 400


def test_register_rejects_weak_password(api_client):
    url = reverse("api:auth-register")
    payload = registration_payload(password="weak", password2="weak")

    response = api_client.post(url, payload, format="json")

    assert response.status_code == 400
    body = response.json()
    assert "password" in str(body)