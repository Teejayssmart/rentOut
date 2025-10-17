# property/propertylist_app/tests/payments/test_payments_and_webhooks.py

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from django.contrib.auth.models import User
from propertylist_app.models import Room, RoomCategorie, Payment

import stripe


@pytest.mark.django_db
def test_stripe_webhook_signature_verification_and_room_extension(monkeypatch):
    owner = User.objects.create_user(username="payowner", password="pass123", email="p@x.com")
    cat = RoomCategorie.objects.create(name="Premium", active=True)
    room = Room.objects.create(title="Luxury Flat", category=cat, price_per_month=950, property_owner=owner)

    payment = Payment.objects.create(
        user=owner, room=room, amount=1.00, currency="GBP", status="created"
    )

    url = reverse("v1:stripe-webhook")

    def fake_construct_event(payload, sig_header, secret):
        return {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_123", "payment_intent": "pi_test_123",
                                "metadata": {"payment_id": str(payment.id)}}},
        }

    monkeypatch.setattr("propertylist_app.api.views.stripe.Webhook.construct_event", fake_construct_event)

    client = APIClient()
    r_ok = client.post(url, {"dummy": True}, format="json", HTTP_STRIPE_SIGNATURE="t=123,v1=validsig")
    assert r_ok.status_code == 200, r_ok.data

    payment.refresh_from_db()
    room.refresh_from_db()
    assert payment.status == "succeeded"
    assert payment.stripe_payment_intent_id == "pi_test_123"
    assert room.paid_until is not None
    assert room.paid_until >= timezone.now().date()

    def fake_construct_event_bad(payload, sig_header, secret):
        raise stripe.error.SignatureVerificationError("bad sig", sig_header)

    monkeypatch.setattr("propertylist_app.api.views.stripe.Webhook.construct_event", fake_construct_event_bad)

    r_bad = client.post(url, {"dummy": True}, format="json", HTTP_STRIPE_SIGNATURE="t=123,v1=invalidsig")
    assert r_bad.status_code == 400, r_bad.data


@pytest.mark.django_db
def test_create_checkout_session_for_room(monkeypatch):
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    cat = RoomCategorie.objects.create(name="Paid", active=True)
    room = Room.objects.create(title="My Listing", category=cat, price_per_month=800, property_owner=owner)

    class FakeSession:
        id = "cs_test_456"

    def fake_session_create(**kwargs):
        return FakeSession()

    monkeypatch.setattr("propertylist_app.api.views.stripe.checkout.Session.create", fake_session_create)

    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("v1:payments-checkout-room", kwargs={"pk": room.pk})
    r = client.post(url, {}, format="json")
    assert r.status_code == 200, r.data
    assert r.data.get("sessionId") == "cs_test_456"
    # publishableKey may be empty if not set in env; just assert the key exists
    assert "publishableKey" in r.data

    p = Payment.objects.get(room=room)
    assert p.stripe_checkout_session_id == "cs_test_456"
    assert p.amount == 1.00
    assert p.status == "created"
