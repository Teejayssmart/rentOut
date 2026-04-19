
# They prove:

# social/no-password users can set a password
# normal users cannot misuse the endpoint
# mismatch and weak password are rejected






import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from propertylist_app.models import UserProfile

pytestmark = pytest.mark.django_db


def make_social_style_user_without_password():
    user = get_user_model().objects.create_user(
        username="socialnopass",
        email="socialnopass@example.com",
        password=None,
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])

    UserProfile.objects.get_or_create(user=user)
    return user


def make_normal_user_with_password():
    user = get_user_model().objects.create_user(
        username="normalpassuser",
        email="normalpass@example.com",
        password="StrongPass1!",
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def test_create_password_for_social_user_succeeds(api_client):
    user = make_social_style_user_without_password()
    url = reverse("api:user-create-password")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "new_password": "NewStrong1!",
            "confirm_password": "NewStrong1!",
        },
        format="json",
    )

    assert response.status_code == 200, response.json()

    user.refresh_from_db()
    assert user.has_usable_password() is True
    assert user.check_password("NewStrong1!")


def test_create_password_rejects_when_user_already_has_password(api_client):
    user = make_normal_user_with_password()
    url = reverse("api:user-create-password")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "new_password": "AnotherStrong1!",
            "confirm_password": "AnotherStrong1!",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()


def test_create_password_rejects_mismatched_confirmation(api_client):
    user = make_social_style_user_without_password()
    url = reverse("api:user-create-password")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "new_password": "NewStrong1!",
            "confirm_password": "Different1!",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()


def test_create_password_rejects_weak_password(api_client):
    user = make_social_style_user_without_password()
    url = reverse("api:user-create-password")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "new_password": "weak",
            "confirm_password": "weak",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()