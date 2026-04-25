import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

API_PREFIX = "/api/v1"


def url_my_notification_preferences():
    return f"{API_PREFIX}/users/me/notification-preferences/"


def test_notification_preferences_get_requires_auth():
    client = APIClient()
    res = client.get(url_my_notification_preferences())
    assert res.status_code in (401, 403)
