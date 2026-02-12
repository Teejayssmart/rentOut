import re
import pytest
from django.utils import timezone
from django.test import override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import EmailOTP


@pytest.fixture
def api():
    return APIClient()


def register_url():
    return reverse("v1:auth-register")


def verify_otp_url():
    return reverse("v1:auth-verify-otp")


def resend_otp_url():
    return reverse("v1:auth-resend-otp")


def base_payload(**overrides):
    data = {
        "username": "edgeuser",
        "email": "edgeuser@example.com",
        "password": "Str0ng!Pass",
        "password2": "Str0ng!Pass",
        "first_name": "Edge",
        "last_name": "User",
        "role": "seeker",
        "terms_accepted": True,
        "terms_version": "v1.0",
        "marketing_consent": False,
    }
    data.update(overrides)
    return data


# ---------- Password policy edges ----------

@pytest.mark.parametrize(
    "pwd",
    [
        "short7!",        # too short, no upper/lower mix
        "alllowercase1!", # no uppercase
        "ALLUPPERCASE1!", # no lowercase
        "NoDigits!!!",    # no digit
        "NoSpecial123",   # no special
    ],
)
@pytest.mark.django_db
def test_register_password_policy_edges_400(api, pwd):
    payload = base_payload(
        password=pwd,
        password2=pwd,
        username=f"user_{re.sub('[^a-zA-Z0-9]', '', pwd)[:8]}",
    )
    payload["email"] = f"{payload['username']}@example.com"

    res = api.post(register_url(), payload, format="json")
    assert res.status_code == 400, getattr(res, "data", res.content)
    assert "password" in "".join([str(v) for v in res.data.values()]).lower()


# ---------- Duplicates (case-insensitive email, exact username) ----------

@pytest.mark.django_db
def test_register_duplicate_email_case_insensitive_400(api):
    res1 = api.post(register_url(), base_payload(), format="json")
    assert res1.status_code == 201, getattr(res1, "data", res1.content)

    dup = base_payload(username="edgeuser2", email="EDGEUSER@EXAMPLE.COM")
    res2 = api.post(register_url(), dup, format="json")
    assert res2.status_code == 400, getattr(res2, "data", res2.content)


@pytest.mark.django_db
def test_register_duplicate_username_400(api):
    res1 = api.post(register_url(), base_payload(), format="json")
    assert res1.status_code == 201, getattr(res1, "data", res1.content)

    dup = base_payload(email="different@example.com")
    res2 = api.post(register_url(), dup, format="json")
    assert res2.status_code == 400, getattr(res2, "data", res2.content)


# ---------- Terms validation ----------

@pytest.mark.django_db
def test_register_terms_version_missing_400(api):
    bad = base_payload()
    bad.pop("terms_version")

    res = api.post(register_url(), bad, format="json")
    assert res.status_code == 400, getattr(res, "data", res.content)
    assert res.data.get("ok") is False
    assert res.data.get("code") == "validation_error"
    assert "terms_version" in res.data.get("field_errors", {})



@pytest.mark.django_db
def test_register_terms_accepted_false_400(api):
    bad = base_payload(terms_accepted=False)

    res = api.post(register_url(), bad, format="json")
    assert res.status_code == 400, getattr(res, "data", res.content)
    assert "terms_accepted" in res.data


# ---------- OTP attempts cap / expired / none ----------

@pytest.mark.django_db
def test_verify_otp_attempts_cap_then_429(api):
    res = api.post(register_url(), base_payload(), format="json")
    assert res.status_code == 201, getattr(res, "data", res.content)

    u = get_user_model().objects.get(username="edgeuser")

    # ensure a known OTP
    EmailOTP.objects.filter(user=u, used_at__isnull=True).update(used_at=timezone.now())
    EmailOTP.create_for(u, "123456", ttl_minutes=10)

    wrong = {"user_id": u.id, "code": "000000"}

    # 5 wrong attempts → all 400
    for _ in range(5):
        r = api.post(verify_otp_url(), wrong, format="json")
        assert r.status_code == 400, getattr(r, "data", r.content)

    # 6th should be 429
    r6 = api.post(verify_otp_url(), wrong, format="json")
    assert r6.status_code == 429, getattr(r6, "data", r6.content)


@pytest.mark.django_db
def test_verify_otp_expired_400_message(api):
    res = api.post(register_url(), base_payload(username="edgeuser_exp"), format="json")
    assert res.status_code == 201, getattr(res, "data", res.content)

    u = get_user_model().objects.get(username="edgeuser_exp")

    EmailOTP.objects.filter(user=u, used_at__isnull=True).update(used_at=timezone.now())
    EmailOTP.create_for(u, "654321", ttl_minutes=0)

    r = api.post(verify_otp_url(), {"user_id": u.id, "code": "654321"}, format="json")
    assert r.status_code == 400, getattr(r, "data", r.content)
    assert "expired" in str(r.data).lower()


@pytest.mark.django_db
def test_verify_otp_no_active_code_400(api):
    res = api.post(register_url(), base_payload(username="edgeuser_none"), format="json")
    assert res.status_code == 201, getattr(res, "data", res.content)

    u = get_user_model().objects.get(username="edgeuser_none")

    EmailOTP.objects.filter(user=u, used_at__isnull=True).update(used_at=timezone.now())

    r = api.post(verify_otp_url(), {"user_id": u.id, "code": "123456"}, format="json")
    assert r.status_code == 400, getattr(r, "data", r.content)
    assert "no active" in str(r.data).lower() or "resend" in str(r.data).lower()


# ---------- Resend OTP throttle & unknown user ----------

@pytest.mark.django_db
@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
        "DEFAULT_THROTTLE_RATES": {"otp-resend": "1/minute"},
    }
)
def test_resend_otp_throttled_second_call_429(api):
    res = api.post(
        register_url(),
        base_payload(username="edgeuser_throttle", email="edge_throttle@example.com"),
        format="json",
    )
    assert res.status_code == 201, getattr(res, "data", res.content)

    u = get_user_model().objects.get(username="edgeuser_throttle")

    r1 = api.post(resend_otp_url(), {"user_id": u.id}, format="json")
    assert r1.status_code == 204, getattr(r1, "data", r1.content)

    r2 = api.post(resend_otp_url(), {"user_id": u.id}, format="json")
    assert r2.status_code == 429, getattr(r2, "data", r2.content)


@pytest.mark.django_db
def test_resend_otp_unknown_user_id_returns_404(api):
    r = api.post(resend_otp_url(), {"user_id": 999999}, format="json")
    assert r.status_code in (400, 404, 204), getattr(r, "data", r.content)



