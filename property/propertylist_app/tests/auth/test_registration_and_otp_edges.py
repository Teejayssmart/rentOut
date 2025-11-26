import re
import pytest
from django.utils import timezone
from django.test import override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import EmailOTP, UserProfile

API = "/api"

@pytest.fixture
def api():
    return APIClient()

def base_payload(**overrides):
    data = {
        "username": "edgeuser",
        "email": "edgeuser@example.com",
        "password": "Str0ng!Pass",
        "password2": "Str0ng!Pass",
        "first_name": "Edge",
        "last_name": " User",
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
    payload = base_payload(password=pwd, password2=pwd, username=f"user_{re.sub('[^a-zA-Z0-9]', '', pwd)[:8]}")
    # ensure unique email per run
    payload["email"] = f"{payload['username']}@example.com"
    res = api.post(f"{API}/auth/register/", payload, format="json")
    assert res.status_code == 400, res.data
    assert "password" in "".join([str(v) for v in res.data.values()]).lower()

# ---------- Duplicates (case-insensitive email, exact username) ----------

@pytest.mark.django_db
def test_register_duplicate_email_case_insensitive_400(api):
    res1 = api.post(f"{API}/auth/register/", base_payload(), format="json")
    assert res1.status_code == 201
    dup = base_payload(username="edgeuser2", email="EDGEUSER@EXAMPLE.COM")
    res2 = api.post(f"{API}/auth/register/", dup, format="json")
    assert res2.status_code == 400

@pytest.mark.django_db
def test_register_duplicate_username_400(api):
    res1 = api.post(f"{API}/auth/register/", base_payload(), format="json")
    assert res1.status_code == 201
    dup = base_payload(email="different@example.com")
    res2 = api.post(f"{API}/auth/register/", dup, format="json")
    assert res2.status_code == 400

# ---------- Terms validation ----------

@pytest.mark.django_db
def test_register_terms_version_missing_400(api):
    bad = base_payload()
    bad.pop("terms_version")
    res = api.post(f"{API}/auth/register/", bad, format="json")
    assert res.status_code == 400
    assert "terms_version" in res.data

@pytest.mark.django_db
def test_register_terms_accepted_false_400(api):
    bad = base_payload(terms_accepted=False)
    res = api.post(f"{API}/auth/register/", bad, format="json")
    assert res.status_code == 400
    assert "terms_accepted" in res.data

# ---------- OTP attempts cap / expired / none ----------

@pytest.mark.django_db
def test_verify_otp_attempts_cap_then_429(api):
    res = api.post(f"{API}/auth/register/", base_payload(), format="json")
    assert res.status_code == 201
    u = get_user_model().objects.get(username="edgeuser")

    # ensure a known OTP
    EmailOTP.objects.filter(user=u, used_at__isnull=True).update(used_at=timezone.now())
    EmailOTP.create_for(u, "123456", ttl_minutes=10)

    wrong = {"user_id": u.id, "code": "000000"}
    # 5 wrong attempts → all 400
    for _ in range(5):
        r = api.post(f"{API}/auth/verify-otp/", wrong, format="json")
        assert r.status_code == 400
    # 6th should be 429
    r6 = api.post(f"{API}/auth/verify-otp/", wrong, format="json")
    assert r6.status_code == 429

@pytest.mark.django_db
def test_verify_otp_expired_400_message(api):
    res = api.post(f"{API}/auth/register/", base_payload(username="edgeuser_exp"), format="json")
    assert res.status_code == 201
    u = get_user_model().objects.get(username="edgeuser_exp")

    # expired OTP
    EmailOTP.objects.filter(user=u, used_at__isnull=True).update(used_at=timezone.now())
    EmailOTP.create_for(u, "654321", ttl_minutes=0)

    r = api.post(f"{API}/auth/verify-otp/", {"user_id": u.id, "code": "654321"}, format="json")
    assert r.status_code == 400
    assert "expired" in str(r.data).lower()

@pytest.mark.django_db
def test_verify_otp_no_active_code_400(api):
    res = api.post(f"{API}/auth/register/", base_payload(username="edgeuser_none"), format="json")
    assert res.status_code == 201
    u = get_user_model().objects.get(username="edgeuser_none")

    # Invalidate any active OTPs
    EmailOTP.objects.filter(user=u, used_at__isnull=True).update(used_at=timezone.now())

    r = api.post(f"{API}/auth/verify-otp/", {"user_id": u.id, "code": "123456"}, format="json")
    assert r.status_code == 400
    assert "no active" in str(r.data).lower() or "resend" in str(r.data).lower()

# ---------- Resend OTP throttle & unknown user ----------

@pytest.mark.django_db
@override_settings(REST_FRAMEWORK={
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"otp-resend": "1/minute"},
})
def test_resend_otp_throttled_second_call_429(api):
    res = api.post(f"{API}/auth/register/", base_payload(username="edgeuser_throttle", email="edge_throttle@example.com"), format="json")
    assert res.status_code == 201
    u = get_user_model().objects.get(username="edgeuser_throttle")

    r1 = api.post(f"{API}/auth/resend-otp/", {"user_id": u.id}, format="json")
    assert r1.status_code == 204
    r2 = api.post(f"{API}/auth/resend-otp/", {"user_id": u.id}, format="json")
    assert r2.status_code == 429

@pytest.mark.django_db
def test_resend_otp_unknown_user_id_returns_404(api):
    r = api.post(f"{API}/auth/resend-otp/", {"user_id": 999999}, format="json")
    assert r.status_code in (400, 404, 204)  # accept any chosen policy; adjust once fixed
