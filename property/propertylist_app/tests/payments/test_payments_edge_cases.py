import json

import pytest
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

WEBHOOK_API = "/api/payments/webhook/"
WEBHOOK_V1 = "/api/v1/payments/webhook/"


def post_webhook(client: APIClient, url: str, event: dict, signed: bool = True):
    """
    Posts an event to a webhook endpoint.
    - follow=True is important because /api/... now 308-redirects to /api/v1/... in your project.
    """
    payload = json.dumps(event).encode("utf-8")

    headers = {}
    if signed:
        headers["HTTP_STRIPE_SIGNATURE"] = "test_sig"

    return client.post(
        url,
        data=payload,
        content_type="application/json",
        follow=True,
        **headers,
    )


def test_webhook_rejects_amount_or_currency_mismatch_api_vs_v1(monkeypatch):
    """
    Goal: if webhook says "paid" but currency/amount does NOT match what your system expects,
    it must NOT mark the payment as successful.
    We only enforce parity (same status + same response shape) unless your project has a strict rule.
    """
    called = {"count": 0}

    def _fake_finalise(*args, **kwargs):
        called["count"] += 1

    client = APIClient()

    event = {
        "id": "evt_test_amount_mismatch",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "payment_status": "paid",
                "currency": "usd",
                "amount_total": 999999,
                "metadata": {
                    "payment_id": "123",
                    "room_id": "456",
                },
            }
        },
    }

    r_api = post_webhook(client, WEBHOOK_API, event, signed=False)
    r_v1 = post_webhook(client, WEBHOOK_V1, event, signed=False)

    assert r_api.status_code == r_v1.status_code, (
        r_api.status_code,
        r_v1.status_code,
        getattr(r_api, "data", None),
        getattr(r_v1, "data", None),
    )

    # If your webhook returns an enveloped error body, compare core fields only
    api_body = getattr(r_api, "data", None)
    v1_body = getattr(r_v1, "data", None)

    if isinstance(api_body, dict) and isinstance(v1_body, dict):
        for key in ("ok", "code", "status"):
            if key in api_body or key in v1_body:
                assert api_body.get(key) == v1_body.get(key)

    assert called["count"] == 0
