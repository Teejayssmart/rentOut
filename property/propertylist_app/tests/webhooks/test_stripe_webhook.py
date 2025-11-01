import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from django.contrib.auth.models import User

from propertylist_app.models import Room, RoomCategorie, Payment

# Import the same module the view uses, and the real stripe module
import propertylist_app.api.views as views_mod
import stripe as real_stripe


@pytest.mark.django_db
def test_valid_signature_updates_payment_once_idempotent(monkeypatch):
    """
    Valid Stripe webhook (checkout.session.completed) must:
      - update the Payment to 'succeeded'
      - set payment_intent id
      - extend the room.paid_until by EXACTLY 30 days
    And if delivered twice, it must NOT extend twice (idempotent).
    """
    # Arrange
    owner = User.objects.create_user(username="payowner", password="pass123", email="p@x.com")
    cat = RoomCategorie.objects.create(name="Premium", active=True)
    room = Room.objects.create(title="Luxury Flat", category=cat, price_per_month=950, property_owner=owner)
    payment = Payment.objects.create(user=owner, room=room, amount=1.00, currency="GBP", status="created")

    url = reverse("v1:stripe-webhook")

    # Ensure the view uses the real stripe module (other tests may mock it)
    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    # Good event (first delivery)
    def good_event(payload, sig_header, secret):
        return {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_1",
                    "payment_intent": "pi_test_123",
                    "metadata": {"payment_id": str(payment.id)},
                }
            },
        }

    # Patch construct_event for GOOD path
    monkeypatch.setattr(views_mod.stripe.Webhook, "construct_event", good_event)

    client = APIClient()
    today = timezone.now().date()

    # Act 1: deliver once
    r1 = client.post(url, data=json.dumps({"ok": True}), content_type="application/json",
                     HTTP_STRIPE_SIGNATURE="t=1,v1=valid")
    assert r1.status_code == 200, r1.content

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == "succeeded"
    assert payment.stripe_payment_intent_id == "pi_test_123"
    assert room.paid_until is not None
    # Should be exactly 30 days from today on first success
    assert room.paid_until == today + timedelta(days=30)

    # Act 2: deliver the SAME success again (idempotency)
    r2 = client.post(url, data=json.dumps({"ok": True}), content_type="application/json",
                     HTTP_STRIPE_SIGNATURE="t=2,v1=valid")
    assert r2.status_code == 200, r2.content

    payment.refresh_from_db()
    room.refresh_from_db()

    # Assert: still succeeded, and NOT extended twice
    assert payment.status == "succeeded"
    assert payment.stripe_payment_intent_id == "pi_test_123"
    assert room.paid_until == today + timedelta(days=30), "Room was extended twice; webhook not idempotent"


@pytest.mark.django_db
def test_invalid_signature_ignored_400(monkeypatch):
    """
    Invalid Stripe signature must be rejected with 400 and must NOT change payment/room.
    """
    owner = User.objects.create_user(username="badowner", password="pass123", email="b@x.com")
    cat = RoomCategorie.objects.create(name="Basic", active=True)
    room = Room.objects.create(title="Test Room", category=cat, price_per_month=500, property_owner=owner)
    payment = Payment.objects.create(user=owner, room=room, amount=1.00, currency="GBP", status="created")

    url = reverse("v1:stripe-webhook")

    # Ensure the view uses real stripe module
    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    # Make construct_event raise the exact class the view catches
    def bad_event(payload, sig_header, secret):
        raise views_mod.stripe.error.SignatureVerificationError("bad sig", sig_header)

    monkeypatch.setattr(views_mod.stripe.Webhook, "construct_event", bad_event)

    client = APIClient()
    before_paid_until = room.paid_until

    r = client.post(url, data=json.dumps({"ok": False}), content_type="application/json",
                    HTTP_STRIPE_SIGNATURE="t=123,v1=invalid")
    assert r.status_code == 400, r.content

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == "created", "Payment status changed on invalid signature"
    assert room.paid_until == before_paid_until, "Room changed on invalid signature"


@pytest.mark.django_db
def test_unknown_event_type_noop_200(monkeypatch):
    """
    Unknown/unsupported event types should be acknowledged (200) but cause no changes.
    """
    owner = User.objects.create_user(username="mystery", password="pass123", email="m@x.com")
    cat = RoomCategorie.objects.create(name="Other", active=True)
    room = Room.objects.create(title="Unknown Case", category=cat, price_per_month=600, property_owner=owner)
    payment = Payment.objects.create(user=owner, room=room, amount=1.00, currency="GBP", status="created")

    url = reverse("v1:stripe-webhook")

    # Ensure the view uses real stripe module
    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    # Return an event your code does not handle explicitly
    def unknown_event(payload, sig_header, secret):
        return {
            "type": "some.unhandled.event",
            "data": {"object": {"id": "evt_unknown", "metadata": {"payment_id": str(payment.id)}}},
        }

    monkeypatch.setattr(views_mod.stripe.Webhook, "construct_event", unknown_event)

    client = APIClient()
    before_status = payment.status
    before_paid_until = room.paid_until

    r = client.post(url, data=json.dumps({"whatever": True}), content_type="application/json",
                    HTTP_STRIPE_SIGNATURE="t=555,v1=valid")
    assert r.status_code == 200, r.content

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == before_status, "Payment changed for unknown event"
    assert room.paid_until == before_paid_until, "Room changed for unknown event"
