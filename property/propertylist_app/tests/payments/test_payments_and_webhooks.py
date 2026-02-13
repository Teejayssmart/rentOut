import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from django.contrib.auth.models import User

from propertylist_app.models import Room, RoomCategorie, Payment

# Import the same module the view uses
import propertylist_app.api.views as views_mod
import stripe as real_stripe


@pytest.mark.django_db
def test_stripe_webhook_signature_verification_and_room_extension(monkeypatch):
    owner = User.objects.create_user(username="payowner", password="pass123", email="p@x.com")
    cat = RoomCategorie.objects.create(name="Premium", active=True)
    room = Room.objects.create(title="Luxury Flat", category=cat, price_per_month=950, property_owner=owner)

    payment = Payment.objects.create(
        user=owner, room=room, amount=1.00, currency="GBP", status="created"
    )

    url = reverse("v1:stripe-webhook")

    # Ensure the view uses the real stripe module (not a MagicMock from other tests)
    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    # --- GOOD signature path ---
    def fake_construct_event(payload, sig_header, secret):
        return {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_123", "payment_intent": "pi_test_123",
                                "metadata": {"payment_id": str(payment.id)}}},
        }

    monkeypatch.setattr(views_mod.stripe.Webhook, "construct_event", fake_construct_event)

    client = APIClient()
    r_ok = client.post(url, {"dummy": True}, format="json", HTTP_STRIPE_SIGNATURE="t=123,v1=validsig")
    assert r_ok.status_code == 200, r_ok.data

    payment.refresh_from_db()
    room.refresh_from_db()
    assert payment.status == "succeeded"
    assert payment.stripe_payment_intent_id == "pi_test_123"
    assert room.paid_until is not None
    assert room.paid_until >= timezone.now().date()

    # --- BAD signature path ---
    def fake_construct_event_bad(payload, sig_header, secret):
        raise views_mod.stripe.error.SignatureVerificationError("bad sig", sig_header)

    monkeypatch.setattr(views_mod.stripe.Webhook, "construct_event", fake_construct_event_bad)

    r_bad = client.post(url, {"dummy": True}, format="json", HTTP_STRIPE_SIGNATURE="t=123,v1=invalidsig")
    assert r_bad.status_code == 400, r_bad.data


@pytest.mark.django_db
def test_create_checkout_session_for_room(monkeypatch):
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    cat = RoomCategorie.objects.create(name="Paid", active=True)
    room = Room.objects.create(title="My Listing", category=cat, price_per_month=800, property_owner=owner)

    class FakeCustomer:
        id = "cus_test_123"

    class FakeSession:
        id = "cs_test_456"
        url = "https://stripe.test/cs_test_456"

    def fake_customer_create(**kwargs):
        return FakeCustomer()

    def fake_session_create(**kwargs):
        return FakeSession()

    # Patch the exact objects your view uses
    monkeypatch.setattr(views_mod.stripe.Customer, "create", fake_customer_create)
    monkeypatch.setattr(views_mod.stripe.checkout.Session, "create", fake_session_create)


    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("v1:payments-checkout-room", kwargs={"pk": room.pk})
    r = client.post(url, {}, format="json")
    assert r.status_code == 200, r.data
    assert r.data.get("session_id") == "cs_test_456"
    assert r.data.get("checkout_url") is not None


    p = Payment.objects.get(room=room)
    assert p.stripe_checkout_session_id == "cs_test_456"
    assert p.amount == 1.00
    assert p.status == "created"
