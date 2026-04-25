import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

API_PREFIX = "/api/v1"


def url_notifications_list():
    return f"{API_PREFIX}/notifications/"


def test_notifications_list_requires_auth():
    client = APIClient()
    res = client.get(url_notifications_list())
    assert res.status_code in (401, 403)
