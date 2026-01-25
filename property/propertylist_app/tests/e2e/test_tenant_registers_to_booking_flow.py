from datetime import timedelta
import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _get_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _extract_otp_code(otp_obj):
    """
    Best-effort extraction: your OTP model may store the value as `code`, `otp`, or similar.
    """
    for attr in ("code", "otp", "token", "value"):
        if hasattr(otp_obj, attr):
            val = getattr(otp_obj, attr)
            if val:
                return val
    raise AssertionError(f"Cannot find OTP code field on {otp_obj.__class__.__name__}")


def _normalise_results(data):
    """
    Handles both list responses and DRF pagination dicts ({"results":[...]}).
    """
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

    # ------------------------------------------------------------
    # Arrange: create an ACTIVE landlord room so search returns it
    # ------------------------------------------------------------
    landlord = user_factory(username="e2e_landlord_b", role="landlord")
    room = room_factory(property_owner=landlord)

    # Ensure listing is "active" for search (paid_until in future)
    if hasattr(room, "paid_until"):
        room.paid_until = timezone.now().date() + timedelta(days=30)
    if hasattr(room, "is_published"):
        room.is_published = True
    room.save()

    # ------------------------------------------------------------
    # Tenant registers (API)
    # endpoint: POST /api/auth/register/
    # ------------------------------------------------------------
    anon = APIClient()

    email = "e2e_tenant_b@test.com"
    username = "e2e_tenant_b"
    password = "Pass12345!"

    register_payload = {
    "email": email,
    "username": username,
    "password": password,
    # keep your existing password confirm key that is currently working
    "terms_accepted": True,
    "terms_version": "v1",
    "role": "seeker",  #  add this
      }



    res = anon.post("/api/auth/register/", data=register_payload, format="json")
    assert res.status_code in (200, 201), res.data
    User = apps.get_model("auth", "User")
    tenant = User.objects.get(username=username)


    # ------------------------------------------------------------
    # OTP verify
    # endpoint: POST /api/auth/verify-otp/
    # ------------------------------------------------------------
    EmailOTP = _get_model("propertylist_app", "EmailOTP")
    assert EmailOTP is not None, "EmailOTP model not found (required for OTP E2E)."

    otp_obj = (
        EmailOTP.objects.filter(email=email).order_by("-id").first()
        if "email" in [f.name for f in EmailOTP._meta.fields]
        else EmailOTP.objects.order_by("-id").first()
    )
    assert otp_obj is not None, "No OTP record created for registration."

    otp_code = _extract_otp_code(otp_obj)

    # Try the most common payload first ("otp"), then fallback to ("code") if required.
    verify_payload = {"user_id": tenant.id, "email": email, "otp": otp_code}
    res = anon.post("/api/auth/verify-otp/", data=verify_payload, format="json")

    if res.status_code == 400 and isinstance(res.data, dict) and "code" in res.data:
        res = anon.post(
            "/api/auth/verify-otp/",
            data={"user_id": tenant.id, "email": email, "code": otp_code},
            format="json",
        )


    assert res.status_code in (200, 204), res.data

    # ------------------------------------------------------------
    # Authenticate tenant client for remaining steps
    # (E2E: after OTP verify, we just act as the verified user)
    # ------------------------------------------------------------
    User = apps.get_model("auth", "User")
    tenant = User.objects.get(username=username)

    tenant_client = APIClient()
    tenant_client.force_authenticate(user=tenant)

    # ------------------------------------------------------------
    # Onboarding complete
    # endpoint: POST /api/users/me/onboarding/complete/
    # ------------------------------------------------------------
    onboarding_payload = {
        # keep minimal; backend should mark onboarding completed
        "confirm": True,
    }
    res = tenant_client.post("/api/users/me/onboarding/complete/", data=onboarding_payload, format="json")
    assert res.status_code in (200, 204), res.data

    # ------------------------------------------------------------
    # Search rooms
    # endpoint: GET /api/search/rooms/
    # ------------------------------------------------------------
    res = tenant_client.get("/api/search/rooms/")
    assert res.status_code == 200, res.data

    items = _normalise_results(res.data)
    assert any(str(item.get("id")) == str(room.id) for item in items), {
        "expected_room_id": room.id,
        "returned_count": len(items),
    }

    # ------------------------------------------------------------
    # Save room toggle
    # endpoint: POST /api/rooms/{room_id}/save-toggle/
    # ------------------------------------------------------------
    res = tenant_client.post(f"/api/rooms/{room.id}/save-toggle/", data={}, format="json")
    assert res.status_code in (200, 201), res.data

    # ------------------------------------------------------------
    # Contact landlord: start a thread from room + send a message
    # endpoint: POST /api/rooms/{room_id}/start-thread/
    # ------------------------------------------------------------
    res = tenant_client.post(
        f"/api/rooms/{room.id}/start-thread/",
        data={"body": "Hi, is the room still available?"},
        format="json",
    )
    assert res.status_code in (200, 201), res.data
    thread_id = res.data.get("id") or res.data.get("thread_id")
    assert thread_id, res.data

    # ------------------------------------------------------------
    # Booking preflight
    # endpoint: POST /api/bookings/create/
    # ------------------------------------------------------------
    start_dt = timezone.now() + timedelta(days=2)
    end_dt = start_dt + timedelta(hours=1)

    res = tenant_client.post(
        "/api/bookings/create/",
        data={
            "room": room.id,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="idem-e2e-b",
    )
    assert res.status_code == 200, res.data

    # ------------------------------------------------------------
    # Create booking
    # endpoint: POST /api/bookings/
    # ------------------------------------------------------------
    res = tenant_client.post(
        "/api/bookings/",
        data={
            "room": room.id,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
        },
        format="json",
    )
    assert res.status_code in (200, 201), res.data

    # ------------------------------------------------------------
    # Notifications list
    # endpoint: GET /api/notifications/
    # ------------------------------------------------------------
    res = tenant_client.get("/api/notifications/")
    assert res.status_code in (200, 204), res.data
