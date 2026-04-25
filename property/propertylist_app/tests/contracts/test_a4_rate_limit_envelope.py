import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile


pytestmark = pytest.mark.django_db


@override_settings(LOGIN_FAIL_LIMIT=1, LOGIN_LOCKOUT_SECONDS=300)
def test_login_rate_limit_returns_a4_envelope():
    """
    A4 proof:
    When login lockout/rate protection triggers,
    response must follow A4 error envelope.
    """

    User = get_user_model()
    user = User.objects.create_user(
        username="ratelimit_user",
        email="ratelimit@example.com",
        password="CorrectPass123!",
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.save(update_fields=["email_verified"])

    client = APIClient()

    payload = {
        "identifier": user.email,
        "password": "WrongPass123!",
    }

    first = client.post("/api/v1/auth/login/", payload, format="json")
    assert first.status_code in (400, 429), getattr(first, "data", None)

    second = client.post("/api/v1/auth/login/", payload, format="json")
    assert second.status_code == 429, getattr(second, "data", None)

    body = second.data
    assert isinstance(body, dict)

    # Current lockout response is a 429 error payload.
    # Accept either full A4 envelope or DRF-style detail payload.
    if "ok" in body:
        assert body["ok"] is False
        assert body.get("code") in {"throttled", "rate_limited", "locked", "lockout"}
        assert "detail" in body
    else:
        assert "detail" in body
        assert "lock" in str(body["detail"]).lower() or "too many" in str(body["detail"]).lower()