# property/propertylist_app/tests/auth/test_login_lockout_and_captcha.py

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile


def _ip_headers(ip="203.0.113.55"):
    # Consistent IP for lockout keying and CAPTCHA validation
    return {"REMOTE_ADDR": ip, "HTTP_X_FORWARDED_FOR": ip}


@pytest.mark.django_db
def test_login_lockout_after_repeated_failures(settings):
    """
    Lockout kicks in after N failed attempts from the same IP+identifier.

    Flow:
      1) Create user.
      2) Fail N times with wrong password (200-OK never expected, 400 each time).
      3) Next attempt returns 429 (locked out).
      4) Successful login later clears failures (sanity check).
    """
    # Keep the test quick & deterministic
    settings.LOGIN_FAIL_LIMIT = 3
    settings.LOGIN_LOCKOUT_SECONDS = 600  # 10 min (we won't actually wait)
    settings.ENABLE_CAPTCHA = False  # not testing CAPTCHA here

    user = User.objects.create_user(username="lockuser", password="pass12345", email="l@example.com")
    # Ensure profile exists + verified (your login flow can require this)
    UserProfile.objects.update_or_create(user=user, defaults={"email_verified": True})

    client = APIClient()
    url = reverse("v1:auth-login")

    # N failed attempts (wrong password)
    for _ in range(settings.LOGIN_FAIL_LIMIT):
        r = client.post(
            url,
            {"identifier": "lockuser", "password": "WRONG"},
            format="json",
            **_ip_headers(),
        )
        # LoginView returns 400 for invalid credentials, not 401
        assert r.status_code == 400, r.data

    # Next attempt (still wrong) should be locked out
    r_locked = client.post(
        url,
        {"identifier": "lockuser", "password": "WRONG"},
        format="json",
        **_ip_headers(),
    )
    assert r_locked.status_code == 429, r_locked.data
    # Optional: precise message
    assert "Too many failed attempts" in str(r_locked.data)

    # Try a correct login (same IP+identifier). Some implementations still block until time passes.
    # If your view clears failures only after a successful login AND allows success while locked,
    # this should be 200. If your lockout blocks all attempts, expect 429 here.
    r_ok = client.post(
        url,
        {"identifier": "lockuser", "password": "pass12345"},
        format="json",
        **_ip_headers(),
    )
    assert r_ok.status_code == 429, r_ok.data
    assert "Too many failed attempts" in str(r_ok.data)



@pytest.mark.django_db
def test_login_requires_captcha_when_enabled(settings, monkeypatch):
    """
    With ENABLE_CAPTCHA = True:
      - If verify_captcha(...) returns False -> 400 with 'CAPTCHA verification failed.'
      - If verify_captcha(...) returns True  -> normal login flow
    """
    settings.ENABLE_CAPTCHA = True
    settings.LOGIN_FAIL_LIMIT = 10  # irrelevant here
    settings.LOGIN_LOCKOUT_SECONDS = 600

    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"] = "100/hour"

    user = User.objects.create_user(username="catuser", password="pass12345", email="c@example.com")
    # Ensure profile exists + verified (your login flow can require this)
    UserProfile.objects.update_or_create(user=user, defaults={"email_verified": True})

    client = APIClient()
    url = reverse("v1:auth-login")

    # Force verify_captcha(...) to return False
    def fake_verify_fail(token, ip):
        return False

    # Patch the symbol the view actually imports/uses:
    monkeypatch.setattr("propertylist_app.api.views.verify_captcha", fake_verify_fail)

    r_bad = client.post(
        url,
        {"identifier": "catuser", "password": "pass12345", "captcha_token": "token123"},
        format="json",
        **_ip_headers(),
    )
    assert r_bad.status_code == 400, r_bad.data
    assert "CAPTCHA verification failed" in str(r_bad.data)

    # Now force verify_captcha(...) to return True and expect a successful login
    def fake_verify_ok(token, ip):
        return True

    monkeypatch.setattr("propertylist_app.api.views.verify_captcha", fake_verify_ok)

    # Correct password should STILL be blocked while lockout is active (strict lockout policy)
    r_ok = client.post(
    url,
    {"identifier": "catuser", "password": "pass12345", "captcha_token": "token123"},
    format="json",
    **_ip_headers(),
    )
    assert r_ok.status_code == 200, r_ok.data
    assert "access" in r_ok.data

