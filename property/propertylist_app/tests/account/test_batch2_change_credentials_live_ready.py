import pytest
from django.contrib.auth import authenticate, get_user_model
from django.urls import reverse

from propertylist_app.models import UserProfile

pytestmark = pytest.mark.django_db

User = get_user_model()


def make_user(username="batch2cred", email="batch2cred@example.com", password="StrongPass1!"):
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def test_change_email_success(api_client):
    user = make_user()
    url = reverse("api:user-change-email")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "current_password": "StrongPass1!",
            "new_email": "newbatch2@example.com",
        },
        format="json",
    )

    assert response.status_code == 200, response.json()

    user.refresh_from_db()
    assert user.email == "newbatch2@example.com"


def test_change_email_rejects_wrong_password(api_client):
    user = make_user()
    url = reverse("api:user-change-email")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "current_password": "WrongPass1!",
            "new_email": "newbatch2@example.com",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()


def test_change_email_rejects_duplicate_email(api_client):
    make_user(username="existingemailuser", email="existing@example.com")
    user = make_user()
    url = reverse("api:user-change-email")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "current_password": "StrongPass1!",
            "new_email": "existing@example.com",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()


def test_change_password_success(api_client):
    user = make_user()
    url = reverse("api:user-change-password")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "current_password": "StrongPass1!",
            "new_password": "NewStrong1!",
            "confirm_password": "NewStrong1!",
        },
        format="json",
    )

    assert response.status_code == 200, response.json()

    user.refresh_from_db()
    assert authenticate(username=user.username, password="StrongPass1!") is None
    assert authenticate(username=user.username, password="NewStrong1!") is not None


def test_change_password_rejects_wrong_current_password(api_client):
    user = make_user()
    url = reverse("api:user-change-password")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "current_password": "WrongPass1!",
            "new_password": "NewStrong1!",
            "confirm_password": "NewStrong1!",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()


def test_change_password_rejects_mismatch(api_client):
    user = make_user()
    url = reverse("api:user-change-password")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "current_password": "StrongPass1!",
            "new_password": "NewStrong1!",
            "confirm_password": "Different1!",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()