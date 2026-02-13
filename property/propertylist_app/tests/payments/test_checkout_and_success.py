from types import SimpleNamespace
import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import Room, Payment


# =========================
# Fixtures (local to file)
# =========================

@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def owner(db):
    User = get_user_model()
    return User.objects.create_user(username="owner", email="o@example.com", password="x")

@pytest.fixture
def room(owner, db):
    return Room.objects.create(
        title="R1",
        description="d",
        price_per_month=500,
        location="SO14",
        property_owner=owner,
        status="active",
        is_available=True,
        paid_until=None,
    )

# =========================
# Tests (aligned to your code)
# =========================

def test_checkout_creates_session_for_owner_room(mocker, owner, room):
    """
    POST /api/v1/payments/checkout/rooms/<pk>/
    Expect: 200, returns sessionId + publishableKey, and a Payment row exists.

    """
    # Your view accesses `session.id` (attribute), so return an object.
    mock_session = SimpleNamespace(id="cs_test_123", url="https://stripe.test/cs_test_123")

    # Patch the `stripe` module used in the view
    views_mod = __import__("propertylist_app.api.views", fromlist=["stripe"])
    mock_stripe = mocker.MagicMock()
    mock_stripe.checkout.Session.create.return_value = mock_session
    views_mod.stripe = mock_stripe

    # Auth using DRF APIClient
    c = APIClient()
    c.force_authenticate(user=owner)

    resp = c.post(
        reverse("v1:payments-checkout-room", kwargs={"pk": room.id}),
        data={"amount": 1000},  # your view ignores and uses a fixed £1, that's fine
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body.get("session_id") == "cs_test_123"
    assert body.get("checkout_url") is not None
    assert Payment.objects.filter(room=room, user=owner).exists()


def test_success_sets_paid_until_and_status_active(mocker, api_client, owner, room):
    """
    Webhook: POST /api/v1/payments/webhook/
    Event: checkout.session.completed -> set Payment to succeeded & extend room.paid_until.
    """
    # Create a Payment row your webhook will find by metadata.payment_id
    payment = Payment.objects.create(user=owner, room=room, amount=1, status="created")

    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_ok",
            "payment_intent": "pi_123",
            "metadata": {"payment_id": str(payment.id)},
        }},
    }

    # Mock signature verification to return our event
    views_mod = __import__("propertylist_app.api.views", fromlist=["stripe"])
    mock_stripe = mocker.MagicMock()
    mock_stripe.Webhook.construct_event.return_value = event
    views_mod.stripe = mock_stripe

    resp = api_client.post(
        reverse("v1:stripe-webhook"),
        data=json.dumps({"anything": "here"}),  # body is ignored by our mock
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content

    payment.refresh_from_db()
    room.refresh_from_db()
    assert payment.status == "succeeded"
    assert payment.stripe_payment_intent_id == "pi_123"
    assert room.paid_until is not None
    assert room.paid_until >= timezone.localdate() + timedelta(days=29)
