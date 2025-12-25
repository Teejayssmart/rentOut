import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile


def prefs_url() -> str:
    return "/api/users/me/notification-preferences/"


def make_user(email: str):
    User = get_user_model()
    username = email.split("@")[0]
    return User.objects.create_user(
        username=username,
        email=email,
        password="pass12345",
    )


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_notification_preferences_requires_auth():
    anon = APIClient()
    res = anon.get(prefs_url())
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_notification_preferences_get_returns_defaults():
    user = make_user("prefs_defaults@example.com")
    client = auth_client(user)

    res = client.get(prefs_url())
    assert res.status_code == 200

    # ensure profile exists and defaults are returned
    assert res.data["marketing_consent"] in (True, False)  # existing field default is your choice
    assert res.data["notify_rentout_updates"] is True
    assert res.data["notify_reminders"] is True
    assert res.data["notify_messages"] is True
    assert res.data["notify_confirmations"] is True


@pytest.mark.django_db
def test_notification_preferences_patch_updates_single_toggle():
    user = make_user("prefs_patch_one@example.com")
    client = auth_client(user)

    res = client.patch(prefs_url(), data={"notify_messages": False}, format="json")
    assert res.status_code == 200
    assert res.data["notify_messages"] is False

    profile = UserProfile.objects.get(user=user)
    assert profile.notify_messages is False


@pytest.mark.django_db
def test_notification_preferences_patch_updates_multiple_toggles():
    user = make_user("prefs_patch_multi@example.com")
    client = auth_client(user)

    payload = {
        "notify_rentout_updates": False,
        "notify_reminders": False,
        "notify_confirmations": False,
        "marketing_consent": True,
    }
    res = client.patch(prefs_url(), data=payload, format="json")
    assert res.status_code == 200

    assert res.data["notify_rentout_updates"] is False
    assert res.data["notify_reminders"] is False
    assert res.data["notify_confirmations"] is False
    assert res.data["marketing_consent"] is True

    profile = UserProfile.objects.get(user=user)
    assert profile.notify_rentout_updates is False
    assert profile.notify_reminders is False
    assert profile.notify_confirmations is False
    assert profile.marketing_consent is True
