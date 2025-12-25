import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile

pytestmark = pytest.mark.django_db

API_PREFIX = "/api"


def url_my_notification_preferences():
    return f"{API_PREFIX}/users/me/notification-preferences/"


def _auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _mk_user(username="u1"):
    User = get_user_model()
    return User.objects.create_user(username=username, password="pass12345")


def test_notification_preferences_get_requires_auth():
    client = APIClient()
    res = client.get(url_my_notification_preferences())
    assert res.status_code in (401, 403)


def test_notification_preferences_get_returns_fields_and_creates_profile_if_missing():
    u1 = _mk_user("u1")

    # in case your project does NOT auto-create profile
    UserProfile.objects.filter(user=u1).delete()

    client = _auth_client(u1)
    res = client.get(url_my_notification_preferences())

    assert res.status_code == 200
    assert "notify_messages" in res.data
    assert "notify_confirmations" in res.data
    assert "notify_reminders" in res.data

    assert UserProfile.objects.filter(user=u1).exists()


def test_notification_preferences_patch_updates_toggles():
    u1 = _mk_user("u1")
    profile, _ = UserProfile.objects.get_or_create(user=u1)

    profile.notify_messages = True
    profile.notify_confirmations = True
    profile.notify_reminders = True
    profile.save()

    client = _auth_client(u1)
    res = client.patch(
        url_my_notification_preferences(),
        data={
            "notify_messages": False,
            "notify_confirmations": False,
            "notify_reminders": True,
        },
        format="json",
    )

    assert res.status_code == 200

    profile.refresh_from_db()
    assert profile.notify_messages is False
    assert profile.notify_confirmations is False
    assert profile.notify_reminders is True
