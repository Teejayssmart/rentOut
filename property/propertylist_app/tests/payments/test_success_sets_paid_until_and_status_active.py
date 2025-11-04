import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from django.contrib.auth.models import User
from propertylist_app.models import Room, RoomCategorie, Payment

# Import the same module your view imports 'stripe' from
import propertylist_app.api.views as views_mod
import stripe as real_stripe


@pytest.mark.django_db
def test_success_sets_paid_until_and_status_active(monkeypatch):
    # Arrange: owner, room, payment in "created"
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    cat = RoomCategorie.objects.create(name="Paid", active=True)
    room = Room.objects.create(
        title="My Listing",
        category=cat,
        price_per_month=800,
        property_owner=owner,
        status="active",  # ensure active precondition
    )

    payment = Payment.objects.create(
        user=owner, room=room, amount=1.00, currency="GBP", status="created"
    )

    client = APIClient()

    # Hit the "success" view (this is what the browser would do after checkout)
    success_url = reverse("v1:payments-success")
    r_success = client.get(success_url, {"session_id": "cs_test_123", "payment_id": str(payment.id)})
    assert r_success.status_code == 200, r_success.content

    # Ensure the view uses the *real* stripe module, then fake the webhook verification
    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    def fake_construct_event(payload, sig_header, secret):
        # Simulate Stripe telling us the checkout succeeded
        return {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_intent": "pi_test_123",
                    "metadata": {"payment_id": str(payment.id)},
                }
            },
        }

    monkeypatch.setattr(views_mod.stripe.Webhook, "construct_event", fake_construct_event)

    # Act: deliver the webhook
    webhook_url = reverse("v1:stripe-webhook")
    r_webhook = client.post(
        webhook_url,
        data=json.dumps({"ok": True}),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=validsig",
    )
    assert r_webhook.status_code == 200, r_webhook.content

    # Assert: payment succeeded, intent saved, room extended & still active
    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == "succeeded"
    assert payment.stripe_payment_intent_id == "pi_test_123"

    assert room.paid_until is not None
    assert room.paid_until >= timezone.now().date()
    # Room should remain active (or be active if you later decide to set it here)
    assert room.status == "active"
