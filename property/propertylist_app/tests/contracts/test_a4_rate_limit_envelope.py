import pytest
from django.test import override_settings
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


@override_settings(
    REST_FRAMEWORK={
        **__import__("django.conf").conf.settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **__import__("django.conf").conf.settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {}),
            "login": "1/min",
        },
    }
)
def test_login_rate_limit_returns_a4_envelope():
    """
    A4 proof:
    When login scope is throttled,
    response must follow A4 error envelope.
    """

    client = APIClient()

    payload = {
        "identifier": "doesnotexist",
        "password": "wrongpass",
    }

    # First request — allowed (will fail auth but consume throttle)
    client.post("/api/auth/login/", payload, format="json")

    # Second request — must trigger throttle
    r = client.post("/api/auth/login/", payload, format="json")

    assert r.status_code == 429, r.data

    assert isinstance(r.data, dict)
    assert r.data.get("ok") is False
    assert r.data.get("code") == "rate_limited"
    assert r.data.get("status") == 429
    assert "message" in r.data
