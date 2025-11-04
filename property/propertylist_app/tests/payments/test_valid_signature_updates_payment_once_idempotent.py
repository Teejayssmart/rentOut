import json
import pytest
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from propertylist_app.models import Room, RoomCategorie, Payment

# Patch the SAME module your view uses
import propertylist_app.api.views as views_mod
import stripe as real_stripe

User = get_user_model()


@pytest.mark.django_db
def test_valid_signature_updates_payment_once_idempotent(monkeypatch):
    """
    When Stripe sends checkout.session.completed:
      - Payment is updated to 'succeeded' with intent id.
      - Room.paid_until is extended by EXACTLY 30 days.
    If the same success is delivered again, it should NOT extend twice.
    """
    # Arrange
    owner = User.objects.create_user(username="payer", password="pass123", email="payer@example.com")
    cat = RoomCategorie.objects.create(name="Paid", active=True)
    room = Room.objects.create(title="Listing 1", category=cat, price_per_month=900, property_owner=owner)
    payment = Payment.objects.create(user=owner, room=room, amount=1.00, currency="GBP", status="created")

    url = reverse("v1:stripe-webhook")

    # Ensure the view uses the real stripe module (not a leftover MagicMock)
    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    def good_event(payload, sig_header, secret):
        # The *same* event content for both deliveries
        return {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_idem",
                    "payment_intent": "pi_test_idem",
                    "metadata": {"payment_id": str(payment.id)},
                }
            },
        }

    # Patch Stripe construct_event
    monkeypatch.setattr(views_mod.stripe.Webhook, "construct_event", good_event)

    client = APIClient()
    today = timezone.now().date()

    # Act 1 — first delivery
    r1 = client.post(
        url,
        data=json.dumps({"ok": True}),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=valid",
    )
    assert r1.status_code == 200

    payment.refresh_from_db()
    room.refresh_from_db()
    assert payment.status == "succeeded"
    assert payment.stripe_payment_intent_id == "pi_test_idem"
    assert room.paid_until == today + timedelta(days=30)

    # Act 2 — same success delivered again (idempotency)
    r2 = client.post(
        url,
        data=json.dumps({"ok": True}),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=2,v1=valid",
    )
    assert r2.status_code == 200

    payment.refresh_from_db()
    room.refresh_from_db()
    # Should remain the same; no double-extension
    assert payment.status == "succeeded"
    assert payment.stripe_payment_intent_id == "pi_test_idem"
    assert room.paid_until == today + timedelta(days=30)
