from datetime import timedelta

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

API = "/api/v1"


def _get_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _extract_otp_code(otp_obj):
    for attr in ("code", "otp", "token", "value"):
        if hasattr(otp_obj, attr):
            val = getattr(otp_obj, attr)
            if val:
                return val
    raise AssertionError(f"Cannot find OTP code field on {otp_obj.__class__.__name__}")


def _normalise_results(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
        return data["results"]
    return []


def test_e2e_tenant_registers_to_booking_flow(user_factory, room_factory):
    """
    End-to-end journey (Tenant):

    register -> verify OTP -> onboarding complete -> search -> save room ->
    start thread -> booking preflight -> create booking -> notifications list
    """

    landlord = user_factory(username="e2e_landlord_b", role="landlord")
    room = room_factory(property_owner=landlord)

    if hasattr(room, "paid_until"):
        room.paid_until = timezone.now().date() + timedelta(days=30)
    if hasattr(room, "is_published"):
        room.is_published = True
    room.save()

    anon = APIClient()

    email = "e2e_tenant_b@test.com"
    username = "e2e_tenant_b"
    password = "Pass12345!"

    register_payload = {
        "email": email,
        "username": username,
        "password": password,
        "terms_accepted": True,
        "terms_version": "v1",
        "role": "seeker",
    }

    res = anon.post(f"{API}/auth/register/", data=register_payload, format="json")
    assert res.status_code in (200, 201), getattr(res, "data", res.content)

    User = apps.get_model("auth", "User")
    tenant = User.objects.get(username=username)

    EmailOTP = _get_model("propertylist_app", "EmailOTP")
    assert EmailOTP is not None, "EmailOTP model not found (required for OTP E2E)."

    otp_obj = EmailOTP.objects.filter(user=tenant).order_by("-id").first()
    assert otp_obj is not None, "No OTP record created for registration."

    otp_code = _extract_otp_code(otp_obj)

    # Your API expects: user_id + code
    res = anon.post(
        f"{API}/auth/verify-otp/",
        data={"user_id": tenant.id, "code": otp_code},
        format="json",
    )
    assert res.status_code in (200, 204), getattr(res, "data", res.content)

    # Login (get JWT)
    res = anon.post(
        f"{API}/auth/login/",
        data={"identifier": email, "password": password},
        format="json",
    )
    assert res.status_code == 200, getattr(res, "data", res.content)

    # Success payload shape in your project: tokens nested
    data = res.data.get("data") if isinstance(res.data, dict) and res.data.get("ok") is True else res.data
    access = None
    if isinstance(data, dict):
        if "access" in data:
            access = data.get("access")
        elif "tokens" in data and isinstance(data["tokens"], dict):
            access = data["tokens"].get("access")
    assert access, data

    # Continue as authenticated user (simple + stable for E2E)
    tenant_client = APIClient()
    tenant_client.force_authenticate(user=tenant)

    res = tenant_client.post(f"{API}/users/me/onboarding/complete/", data={"confirm": True}, format="json")
    assert res.status_code in (200, 204), getattr(res, "data", res.content)

    res = tenant_client.get(f"{API}/search/rooms/")
    assert res.status_code == 200, getattr(res, "data", res.content)

    items = _normalise_results(res.data)
    assert any(str(item.get("id")) == str(room.id) for item in items)

    res = tenant_client.post(f"{API}/rooms/{room.id}/save-toggle/", data={}, format="json")
    assert res.status_code in (200, 201), getattr(res, "data", res.content)

    res = tenant_client.post(
        f"{API}/rooms/{room.id}/start-thread/",
        data={"body": "Hi, is the room still available?"},
        format="json",
    )
    assert res.status_code in (200, 201), getattr(res, "data", res.content)

    payload = res.data.get("data") if isinstance(res.data, dict) and res.data.get("ok") is True else res.data
    thread_id = payload.get("id") or payload.get("thread_id")
    assert thread_id, payload

    start_dt = timezone.now() + timedelta(days=2)
    end_dt = start_dt + timedelta(hours=1)

    res = tenant_client.post(
        f"{API}/bookings/create/",
        data={"room": room.id, "start": start_dt.isoformat(), "end": end_dt.isoformat()},
        format="json",
        HTTP_IDEMPOTENCY_KEY="idem-e2e-b",
    )
    assert res.status_code == 200, getattr(res, "data", res.content)

    res = tenant_client.post(
        f"{API}/bookings/",
        data={"room": room.id, "start": start_dt.isoformat(), "end": end_dt.isoformat()},
        format="json",
    )
    assert res.status_code in (200, 201), getattr(res, "data", res.content)

    res = tenant_client.get(f"{API}/notifications/")
    assert res.status_code in (200, 204), getattr(res, "data", res.content)
