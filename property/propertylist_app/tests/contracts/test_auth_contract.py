import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import EmailOTP


pytestmark = pytest.mark.django_db


# ----------------------------
# Helpers
# ----------------------------
def assert_exact_keys(obj: dict, expected_keys: set[str]) -> None:
    assert isinstance(obj, dict), f"Expected dict, got {type(obj)}"
    assert set(obj.keys()) == expected_keys, f"Keys mismatch.\nGot: {set(obj.keys())}\nExpected: {expected_keys}"


def assert_is_str(value, field_name: str) -> None:
    assert isinstance(value, str), f"{field_name} must be str, got {type(value)}"


def post_json(client: APIClient, url: str, payload: dict):
    return client.post(url, payload, format="json")


# ----------------------------
# Contracts: Register
# ----------------------------
def test_register_contract_api_and_v1_match_shape():
    """
    Contract (from RegistrationSerializer.to_representation):
    {"id": int, "username": str, "email": str, "email_masked": str, "need_otp": bool}
    """
    client = APIClient()

    payload_api = {
        "username": "contractuser_api",
        "email": "contractuser_api@test.com",
        "password": "StrongP@ssword1",
        "password2": "StrongP@ssword1",
        "role": "seeker",
        "terms_accepted": True,
        "terms_version": "v1",
        "marketing_consent": False,
    }

    # /api/
    url_api = reverse("api:auth-register")
    r_api = post_json(client, url_api, payload_api)
    assert r_api.status_code in (200, 201), r_api.data
    data_api = r_api.json()

    expected_keys = {"id", "username", "email", "email_masked", "need_otp"}
    assert_exact_keys(data_api, expected_keys)
    assert isinstance(data_api["id"], int)
    assert_is_str(data_api["username"], "username")
    assert_is_str(data_api["email"], "email")
    assert_is_str(data_api["email_masked"], "email_masked")
    assert isinstance(data_api["need_otp"], bool)

    # /api/v1/ (must use a unique email/username)
    payload_v1 = {
        **payload_api,
        "username": "contractuser_v1",
        "email": "contractuser_v1@test.com",
    }
    url_v1 = reverse("v1:auth-register")
    r_v1 = post_json(client, url_v1, payload_v1)
    assert r_v1.status_code in (200, 201), r_v1.data
    data_v1 = r_v1.json()

    assert_exact_keys(data_v1, expected_keys)

    # Parity check (types and keys only)
    assert isinstance(data_v1["id"], int)
    assert_is_str(data_v1["username"], "username")
    assert_is_str(data_v1["email"], "email")
    assert_is_str(data_v1["email_masked"], "email_masked")
    assert isinstance(data_v1["need_otp"], bool)


# ----------------------------
# Contracts: Verify OTP
# ----------------------------
def test_verify_otp_contract_success_and_failure_api_and_v1():
    """
    Observed contracts:
    Success: {"detail": "Email verified."}
    Failure: {"detail": "No active code. Please resend."}
    """
    client = APIClient()

    # Register one user on /api/ and one user on /api/v1/ so OTP exists
    reg_api = post_json(
        client,
        reverse("api:auth-register"),
        {
            "username": "otp_user_api",
            "email": "otp_user_api@test.com",
            "password": "StrongP@ssword1",
            "password2": "StrongP@ssword1",
            "role": "seeker",
            "terms_accepted": True,
            "terms_version": "v1",
            "marketing_consent": False,
        },
    )
    assert reg_api.status_code in (200, 201), reg_api.data
    user_id_api = reg_api.json()["id"]

    reg_v1 = post_json(
        client,
        reverse("v1:auth-register"),
        {
            "username": "otp_user_v1",
            "email": "otp_user_v1@test.com",
            "password": "StrongP@ssword1",
            "password2": "StrongP@ssword1",
            "role": "seeker",
            "terms_accepted": True,
            "terms_version": "v1",
            "marketing_consent": False,
        },
    )
    assert reg_v1.status_code in (200, 201), reg_v1.data
    user_id_v1 = reg_v1.json()["id"]

    # Pull latest OTP codes from DB
    otp_api = EmailOTP.objects.filter(user_id=user_id_api).order_by("-created_at").first()
    otp_v1 = EmailOTP.objects.filter(user_id=user_id_v1).order_by("-created_at").first()
    assert otp_api and otp_api.code
    assert otp_v1 and otp_v1.code

    # --- /api/ verify success
    r_ok_api = post_json(
        client,
        reverse("api:auth-verify-otp"),
        {"user_id": user_id_api, "code": otp_api.code},
    )
    assert r_ok_api.status_code == 200, r_ok_api.data
    data_ok_api = r_ok_api.json()
    assert_exact_keys(data_ok_api, {"detail"})
    assert_is_str(data_ok_api["detail"], "detail")

    # --- /api/ verify failure (wrong code)
    r_bad_api = post_json(
        client,
        reverse("api:auth-verify-otp"),
        {"user_id": user_id_api, "code": "000000"},
    )
    assert r_bad_api.status_code in (400, 404), r_bad_api.data
    data_bad_api = r_bad_api.json()
    assert_exact_keys(data_bad_api, {"detail"})
    assert_is_str(data_bad_api["detail"], "detail")

    # --- /api/v1/ verify success
    r_ok_v1 = post_json(
        client,
        reverse("v1:auth-verify-otp"),
        {"user_id": user_id_v1, "code": otp_v1.code},
    )
    assert r_ok_v1.status_code == 200, r_ok_v1.data
    data_ok_v1 = r_ok_v1.json()
    assert_exact_keys(data_ok_v1, {"detail"})
    assert_is_str(data_ok_v1["detail"], "detail")

    # Parity: same key set on success
    assert set(data_ok_api.keys()) == set(data_ok_v1.keys()) == {"detail"}


# ----------------------------
# Contracts: Login
# ----------------------------
def test_login_contract_success_and_failure_api():
    """
    Observed contracts:
    Success: {"ok": True, "data": {"tokens": {...}, "user": {...}, "profile": {...}}}
    Failure: {"detail": "Invalid credentials."}  (wrapped by your error envelope in some cases)
    """
    client = APIClient()

    # Register + verify OTP first, because your system blocks login before OTP.
    reg = post_json(
        client,
        reverse("api:auth-register"),
        {
            "username": "login_user_api",
            "email": "login_user_api@test.com",
            "password": "StrongP@ssword1",
            "password2": "StrongP@ssword1",
            "role": "seeker",
            "terms_accepted": True,
            "terms_version": "v1",
            "marketing_consent": False,
        },
    )
    assert reg.status_code in (200, 201), reg.data
    user_id = reg.json()["id"]

    otp = EmailOTP.objects.filter(user_id=user_id).order_by("-created_at").first()
    assert otp and otp.code

    r_verify = post_json(
        client,
        reverse("api:auth-verify-otp"),
        {"user_id": user_id, "code": otp.code},
    )
    assert r_verify.status_code == 200, r_verify.data

    # Login success
    r_ok = post_json(
        client,
        reverse("api:auth-login"),
        {"identifier": "login_user_api", "password": "StrongP@ssword1"},
    )
    assert r_ok.status_code == 200, r_ok.data
    data_ok = r_ok.json()

    assert_exact_keys(data_ok, {"ok", "data"})
    assert data_ok["ok"] is True
    assert_exact_keys(data_ok["data"], {"tokens", "user", "profile"})
    assert_exact_keys(
        data_ok["data"]["tokens"],
        {"access", "refresh", "access_expires_at", "refresh_expires_at"},
    )

    tokens = data_ok["data"]["tokens"]
    assert_is_str(tokens["refresh"], "refresh")
    assert_is_str(tokens["access"], "access")

    # Login failure
    r_bad = post_json(
        client,
        reverse("api:auth-login"),
        {"identifier": "login_user_api", "password": "WrongPassword123"},
    )
    assert r_bad.status_code in (400, 401), r_bad.data
    data_bad = r_bad.json()

    # Some endpoints return {"detail": "..."}; others may wrap errors.
    # Keep your existing contract expectation.
    assert_exact_keys(data_bad, {"detail"})
    assert_is_str(data_bad["detail"], "detail")
