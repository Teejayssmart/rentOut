# property/propertylist_app/tests/auth/test_login_lockout_and_captcha.py

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient


def _ip_headers(ip="203.0.113.55"):
    # Consistent IP for lockout keying and CAPTCHA validation
    return {"REMOTE_ADDR": ip, "HTTP_X_FORWARDED_FOR": ip}


@pytest.mark.django_db
def test_login_lockout_after_repeated_failures(settings):
    """
    Lockout kicks in after N failed attempts from the same IP+username.

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

    client = APIClient()
    url = reverse("v1:auth-login")

    # 3 failed attempts (wrong password)
    for i in range(settings.LOGIN_FAIL_LIMIT):
        r = client.post(
            url,
            {"username": "lockuser", "password": "WRONG"},
            format="json",
            **_ip_headers(),
        )
        # LoginView returns 400 for invalid credentials, not 401
        assert r.status_code == 400, r.data

    # Next attempt (still wrong) should be locked out
    r_locked = client.post(
        url,
        {"username": "lockuser", "password": "WRONG"},
        format="json",
        **_ip_headers(),
    )
    assert r_locked.status_code == 429, r_locked.data
    # Optional: precise message
    assert "Too many failed attempts" in str(r_locked.data)

    # Now try a correct login (from same IP+username).
    # If your lockout implementation clears only on success and isn't time-based here,
    # you may still get 429. But your LoginView clears failures on success,
    # so once we succeed once, future attempts should be fine.
    r_ok = client.post(
        url,
        {"username": "lockuser", "password": "pass12345"},
        format="json",
        **_ip_headers(),
    )
    # If your lockout says "still locked" on success, this would be 429.
    # In your LoginView the success path clears failures and returns 200 with tokens.
    assert r_ok.status_code == 200, r_ok.data
    assert "access" in r_ok.data and "refresh" in r_ok.data


@pytest.mark.django_db
def test_login_requires_captcha_when_enabled(settings, monkeypatch):
    """
    With ENABLE_CAPTCHA = True:
      - If verify_captcha(...) returns False -> 400 with 'CAPTCHA verification failed.'
      - If verify_captcha(...) returns True  -> normal login flow
    """
    settings.ENABLE_CAPTCHA = True
    settings.LOGIN_FAIL_LIMIT = 5  # irrelevant here
    settings.LOGIN_LOCKOUT_SECONDS = 600

    user = User.objects.create_user(username="catuser", password="pass12345", email="c@example.com")
    client = APIClient()
    url = reverse("v1:auth-login")

    # Force verify_captcha(...) to return False
    def fake_verify_fail(token, ip):
        return False

    # Patch the symbol the view actually imports/uses:
    monkeypatch.setattr("propertylist_app.api.views.verify_captcha", fake_verify_fail)

    r_bad = client.post(
        url,
        {"username": "catuser", "password": "pass12345", "captcha_token": "token123"},
        format="json",
        **_ip_headers(),
    )
    assert r_bad.status_code == 400, r_bad.data
    assert "CAPTCHA verification failed" in str(r_bad.data)

    # Now force verify_captcha(...) to return True and expect a successful login
    def fake_verify_ok(token, ip):
        return True

    monkeypatch.setattr("propertylist_app.api.views.verify_captcha", fake_verify_ok)

    r_ok = client.post(
        url,
        {"username": "catuser", "password": "pass12345", "captcha_token": "token123"},
        format="json",
        **_ip_headers(),
    )
    assert r_ok.status_code == 200, r_ok.data
    assert "access" in r_ok.data and "refresh" in r_ok.data
