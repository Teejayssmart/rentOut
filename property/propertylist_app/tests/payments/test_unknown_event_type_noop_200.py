import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from django.contrib.auth.models import User
from propertylist_app.models import Room, RoomCategorie, Payment

import propertylist_app.api.views as views_mod
import stripe as real_stripe


@pytest.mark.django_db
def test_unknown_event_type_noop_200(monkeypatch):
    """
    If Stripe sends an unknown event type, the webhook must:
      - return HTTP 200 (acknowledge receipt)
      - NOT alter any Payment or Room record
      - avoid raising an exception or 500 error
    """
    # Arrange: Create user, room, and pending payment
    owner = User.objects.create_user(username="unknown_evt", password="pass123", email="u@x.com")
    cat = RoomCategorie.objects.create(name="TestCat", active=True)
    room = Room.objects.create(title="UnknownEvt Room", category=cat, price_per_month=900, property_owner=owner)

    payment = Payment.objects.create(
        user=owner, room=room, amount=1.00, currency="GBP", status="created"
    )

    url = reverse("v1:stripe-webhook")
    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    # Fake a valid webhook with an *unknown* event type
    def fake_construct_event(payload, sig_header, secret):
        return {
            "type": "random.event.ignored",
            "data": {"object": {"id": "evt_test_123", "metadata": {"payment_id": str(payment.id)}}},
        }

    monkeypatch.setattr(views_mod.stripe.Webhook, "construct_event", fake_construct_event)

    client = APIClient()

    # Act
    resp = client.post(url, {"dummy": True}, format="json", HTTP_STRIPE_SIGNATURE="t=123,v1=fake")

    # Assert
    assert resp.status_code == 200, resp.content  # must ACK gracefully
    payment.refresh_from_db()
    room.refresh_from_db()

    # Payment and room must remain untouched
    assert payment.status == "created"
    assert payment.stripe_payment_intent_id in (None, "")
    assert room.paid_until in (None, "")
