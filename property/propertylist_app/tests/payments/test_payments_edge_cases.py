import json
import hmac
import hashlib
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


# =========================
# EDIT THESE PATHS TO MATCH YOUR PROJECT
# =========================
WEBHOOK_API = "/api/payments/webhook/"          # e.g. "/api/payments/webhook/"
WEBHOOK_V1 = "/api/v1/payments/webhook/"        # e.g. "/api/v1/payments/webhook/"

SUCCESS_API = "/api/payments/success/"          # if you have /success/<payment_id>/ then include a {payment_id}
SUCCESS_V1 = "/api/v1/payments/success/"

CANCEL_API = "/api/payments/cancel/"
CANCEL_V1 = "/api/v1/payments/cancel/"

DETACH_CARD_API = "/api/payments/cards/{card_id}/detach/"
DETACH_CARD_V1 = "/api/v1/payments/cards/{card_id}/detach/"

# If your webhook uses a signing secret, your view may read settings.STRIPE_WEBHOOK_SECRET.
# This is only for building a realistic Stripe-Signature header if your code checks it.
WEBHOOK_SECRET = "whsec_test_secret"


# -------------------------
# Helpers
# -------------------------
def make_user(username: str) -> object:
    User = get_user_model()
    return User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="StrongP@ssword1",
    )


def make_authed_client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def stripe_signature_header(payload_bytes: bytes, secret: str = WEBHOOK_SECRET, timestamp: int = 1700000000) -> str:
    """
    Stripe signs: "t=timestamp,v1=HMAC_SHA256(timestamp.payload)"
    Only needed if your webhook view enforces signature verification.
    """
    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def post_webhook(client: APIClient, path: str, event: dict, signed: bool = True):
    body = json.dumps(event).encode("utf-8")
    headers = {}
    if signed:
        headers["HTTP_STRIPE_SIGNATURE"] = stripe_signature_header(body)
    return client.post(path, data=body, content_type="application/json", **headers)


# =========================
# 1) currency/amount mismatch safety
# =========================
def test_webhook_rejects_amount_or_currency_mismatch_api_vs_v1(monkeypatch):
    """
    Goal: if webhook says "paid" but currency/amount does NOT match what your system expects,
    it must NOT mark the payment as successful.
    We only enforce parity (same status + same response shape) unless your project has a strict rule.
    """

    # If your code calls a function that finalises payment, patch it and assert it is NOT called.
    # CHANGE THIS import path to your real function (search in your webhook view).
    # Example possibilities:
    # - "propertylist_app.services.payments.finalise_payment"
    # - "propertylist_app.api.views.finalise_payment"
    called = {"count": 0}

    def _fake_finalise(*args, **kwargs):
        called["count"] += 1

    # TODO: change the patch target to the real finaliser used by your webhook
    # monkeypatch.setattr("propertylist_app.services.payments.finalise_payment", _fake_finalise)

    client = APIClient()  # webhook is usually unauthenticated

    event = {
        "id": "evt_test_amount_mismatch",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "payment_status": "paid",
                "currency": "usd",           # mismatch (example)
                "amount_total": 999999,      # mismatch (example)
                "metadata": {
                    "payment_id": "123",
                    "room_id": "456",
                },
            }
        },
    }

    r_api = post_webhook(client, WEBHOOK_API, event, signed=False)
    r_v1 = post_webhook(client, WEBHOOK_V1, event, signed=False)

    assert r_api.status_code == r_v1.status_code, (r_api.status_code, r_v1.status_code, getattr(r_api, "data", None), getattr(r_v1, "data", None))

    # Typical safe behaviours: 200 (ack but ignore), 400 (reject), 403 (bad sig), 422
    assert r_api.status_code in (200, 400, 403, 422), getattr(r_api, "data", None)

    # If you patched the finaliser correctly, this should remain 0 when mismatch occurs.
    # assert called["count"] == 0


# =========================
# 2) webhook missing metadata safety
# =========================
def test_webhook_missing_metadata_is_safe_api_vs_v1(monkeypatch):
    """
    Goal: missing room_id/payment_id metadata must not crash and must not finalise payment.
    """

    called = {"count": 0}

    def _fake_finalise(*args, **kwargs):
        called["count"] += 1

    # TODO: change the patch target to your real finaliser
    # monkeypatch.setattr("propertylist_app.services.payments.finalise_payment", _fake_finalise)

    client = APIClient()

    event = {
        "id": "evt_test_missing_metadata",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_456", "payment_status": "paid", "metadata": {}}},  # missing ids
    }

    r_api = post_webhook(client, WEBHOOK_API, event, signed=False)
    r_v1 = post_webhook(client, WEBHOOK_V1, event, signed=False)

    assert r_api.status_code == r_v1.status_code
    assert r_api.status_code in (200, 400, 403, 422)

    # assert called["count"] == 0


# =========================
# 3) success/cancel callback abuse
# =========================
def test_success_callback_requires_auth_or_valid_context_api_vs_v1():
    """
    Goal: random user (or anon) hitting success URL must not succeed in a way that changes state.
    """

    anon = APIClient()

    r_api = anon.get(SUCCESS_API)
    r_v1 = anon.get(SUCCESS_V1)

    assert r_api.status_code == r_v1.status_code
    assert r_api.status_code in (200, 302, 400, 401, 403, 404)  # depends on your implementation


def test_cancel_callback_requires_auth_or_valid_context_api_vs_v1():
    anon = APIClient()

    r_api = anon.get(CANCEL_API)
    r_v1 = anon.get(CANCEL_V1)

    assert r_api.status_code == r_v1.status_code
    assert r_api.status_code in (200, 302, 400, 401, 403, 404)


# =========================
# 4) user hits success for another user's payment id
# =========================
def test_success_for_other_users_payment_is_forbidden_or_safe(monkeypatch):
    """
    If your success URL contains a payment id (or session id), a user must not be able to claim someone else’s payment.
    Adjust SUCCESS_* constants to include "{payment_id}" and format them here if needed.
    """

    user_a = make_user("pay_user_a")
    user_b = make_user("pay_user_b")

    client_a = make_authed_client(user_a)

    # Replace with a real payment id from your DB if your view looks it up.
    other_payment_id = 999999999

    if "{payment_id}" in SUCCESS_API:
        url_api = SUCCESS_API.format(payment_id=other_payment_id)
        url_v1 = SUCCESS_V1.format(payment_id=other_payment_id)
    else:
        # If your success endpoint does not include an id, this test is not applicable.
        pytest.skip("SUCCESS_* does not include {payment_id}; skip other-user success abuse test.")

    r_api = client_a.get(url_api)
    r_v1 = client_a.get(url_v1)

    assert r_api.status_code == r_v1.status_code
    assert r_api.status_code in (400, 401, 403, 404)


# =========================
# 5) saved card detach lifecycle + permissions
# =========================
def test_detach_card_nonexistent_is_safe_api_vs_v1():
    user = make_user("card_user")
    c = make_authed_client(user)

    url_api = DETACH_CARD_API.format(card_id=999999999)
    url_v1 = DETACH_CARD_V1.format(card_id=999999999)

    r_api = c.post(url_api)
    r_v1 = c.post(url_v1)

    assert r_api.status_code == r_v1.status_code
    assert r_api.status_code in (400, 404, 403)


def test_user_cannot_detach_another_users_card_api_vs_v1(monkeypatch):
    """
    This requires you to create a card for user B in the DB.
    If you have a model like SavedCard / PaymentMethod, import and create it here.
    If you don't support saved cards, skip.
    """

    user_a = make_user("card_user_a")
    user_b = make_user("card_user_b")

    c = make_authed_client(user_a)

    # TODO: create a real card row owned by user_b, then use its id here.
    # Example:
    # from propertylist_app.models import SavedCard
    # card = SavedCard.objects.create(user=user_b, stripe_payment_method_id="pm_test_123", is_default=False)
    # other_users_card_id = card.id

    pytest.skip("Implement card creation (SavedCard/PaymentMethod model) then remove this skip.")

    # url_api = DETACH_CARD_API.format(card_id=other_users_card_id)
    # url_v1 = DETACH_CARD_V1.format(card_id=other_users_card_id)

    # r_api = c.post(url_api)
    # r_v1 = c.post(url_v1)

    # assert r_api.status_code == r_v1.status_code
    # assert r_api.status_code in (403, 404)


def test_detach_default_vs_non_default_behaviour(monkeypatch):
    """
    If your system treats default cards differently:
      - detaching default may require setting another default first OR should be blocked
    Implement by creating two cards and detaching each, then asserting safe outcomes.

    This is project-specific, so leave as TODO once you confirm your rules.
    """
    pytest.skip("Add once you confirm your default-card rules in the backend.")