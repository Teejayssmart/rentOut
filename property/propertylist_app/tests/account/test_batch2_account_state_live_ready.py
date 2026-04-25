import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from propertylist_app.models import UserProfile

pytestmark = pytest.mark.django_db

User = get_user_model()


def make_user():
    user = User.objects.create_user(
        username="batch2account",
        email="batch2account@example.com",
        password="StrongPass1!",
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def test_deactivate_account_sets_user_inactive(api_client):
    user = make_user()
    url = reverse("api:user-deactivate")

    api_client.force_authenticate(user=user)
    response = api_client.post(url, format="json")

    assert response.status_code == 200, response.json()

    user.refresh_from_db()
    assert user.is_active is False


@override_settings(ACCOUNT_DELETION_GRACE_DAYS=7)
def test_delete_account_request_sets_pending_fields_and_deactivates(api_client):
    user = make_user()
    url = reverse("api:user-delete-account")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "confirm": True,
            "current_password": "StrongPass1!",
        },
        format="json",
    )

    assert response.status_code == 200, response.json()
    body = response.json()

    assert body["ok"] is True
    assert body["data"]["detail"] == "Account scheduled for deletion."
    assert body["data"]["grace_days"] == 7

    user.refresh_from_db()
    profile = UserProfile.objects.get(user=user)

    assert user.is_active is False
    assert profile.pending_deletion_requested_at is not None
    assert profile.pending_deletion_scheduled_for is not None


def test_delete_account_request_rejects_wrong_password(api_client):
    user = make_user()
    url = reverse("api:user-delete-account")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {
            "confirm": True,
            "current_password": "WrongPass1!",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()


def test_delete_account_cancel_reactivates_and_clears_pending_fields(api_client):
    user = make_user()
    profile = UserProfile.objects.get(user=user)

    delete_url = reverse("api:user-delete-account")
    cancel_url = reverse("api:user-delete-account-cancel")

    api_client.force_authenticate(user=user)

    delete_response = api_client.post(
        delete_url,
        {
            "confirm": True,
            "current_password": "StrongPass1!",
        },
        format="json",
    )
    assert delete_response.status_code == 200, delete_response.json()

    cancel_response = api_client.post(
        cancel_url,
        {"confirm": True},
        format="json",
    )
    assert cancel_response.status_code == 200, cancel_response.json()

    user.refresh_from_db()
    profile.refresh_from_db()

    assert user.is_active is True
    assert profile.pending_deletion_requested_at is None
    assert profile.pending_deletion_scheduled_for is None


def test_delete_account_cancel_requires_confirm(api_client):
    user = make_user()
    url = reverse("api:user-delete-account-cancel")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {"confirm": False},
        format="json",
    )

    assert response.status_code == 400, response.json()