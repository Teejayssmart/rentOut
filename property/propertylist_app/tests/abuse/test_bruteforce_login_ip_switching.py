import pytest
from django.contrib.auth.models import User
from django.core.cache import caches
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _ip_headers(ip: str):
    # Use REMOTE_ADDR only (matches your lockout logic and avoids XFF ambiguity)
    return {"REMOTE_ADDR": ip}


def test_login_throttle_triggers_and_ip_switching_gets_new_bucket(settings):
    """
    Abuse pattern:
    - brute force from IP1 until DRF throttle triggers (429)
    - switch to IP2 -> not throttled immediately (fresh bucket)

    Backend:
    - LoginView uses ScopedRateThrottle with throttle_scope = "login"
    """
    # Clear any leftover throttle counters
    caches["default"].clear()

    # Narrow throttle rate for a fast deterministic test
    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"] = "2/min"

    User.objects.create_user(
        username="victim_user",
        email="victim@test.com",
        password="CorrectPass123!",
    )

    client = APIClient()
    url = "/api/v1/auth/login/"
    payload = {"username": "victim_user", "password": "WrongPass123!"}

    ip1 = "198.51.100.10"
    ip2 = "198.51.100.11"

    r1 = client.post(url, payload, format="json", **_ip_headers(ip1))
    assert r1.status_code == 400, getattr(r1, "data", r1.content)


    r2 = client.post(url, payload, format="json", **_ip_headers(ip1))
    assert r2.status_code == 400, r2.data

    # Third request must be throttled by DRF ScopedRateThrottle (rate = 2/min)
    r3 = client.post(url, payload, format="json", **_ip_headers(ip1))
    assert r3.status_code == 429, r3.data

    # Switch IP -> should not be throttled immediately
    r4 = client.post(url, payload, format="json", **_ip_headers(ip2))
    assert r4.status_code == 400, r4.data
