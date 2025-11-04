import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from django.contrib.auth.models import User
from propertylist_app.models import Room, RoomCategorie, Payment

# Import the SAME module your view uses for stripe
import propertylist_app.api.views as views_mod
import stripe as real_stripe


@pytest.mark.django_db
def test_invalid_signature_ignored_400(monkeypatch):
    """
    Webhook with an invalid Stripe signature must:
      - return 400 (rejected)
      - NOT update the Payment record
      - NOT change the room's paid_until
    """
    # Arrange: a room + a pending payment
    owner = User.objects.create_user(username="payowner", password="pass123", email="p@x.com")
    cat = RoomCategorie.objects.create(name="Premium", active=True)
    room = Room.objects.create(title="Luxury Flat", category=cat, price_per_month=950, property_owner=owner)

    payment = Payment.objects.create(
        user=owner, room=room, amount=1.00, currency="GBP", status="created"
    )

    url = reverse("v1:stripe-webhook")

    # Ensure we are patching the real stripe module reference used inside the view
    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    # Force Webhook.construct_event to raise the exact SignatureVerificationError class
    def construct_event_bad(payload, sig_header, secret):
        raise views_mod.stripe.error.SignatureVerificationError("bad sig", sig_header)

    monkeypatch.setattr(views_mod.stripe.Webhook, "construct_event", construct_event_bad)

    client = APIClient()

    # Act: post with a bogus signature
    resp = client.post(url, {"any": "payload"}, format="json", HTTP_STRIPE_SIGNATURE="t=1,v1=bogus")
    assert resp.status_code == 400, resp.content  # must reject with 400

    # Assert: payment unchanged, room not extended
    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == "created"
    assert payment.stripe_payment_intent_id in (None, "")
    assert room.paid_until in (None, "") or room.paid_until <= timezone.now().date()
