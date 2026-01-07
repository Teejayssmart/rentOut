from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Notification, Payment

pytestmark = pytest.mark.django_db


def test_stripe_webhook_duplicate_delivery_is_idempotent(monkeypatch, user_factory, room_factory):
    """
    Concurrency/idempotency test:
    - Stripe webhook for checkout.session.completed can arrive more than once.
    Expected:
    - Payment transitions to succeeded only once
    - Room.paid_until is extended only once (+30 days, not +60)
    - "Payment confirmed" notification is created only once
    """
    landlord = user_factory(username="payer1", role="landlord")
    room = room_factory(property_owner=landlord)

    # Make paid_until deterministic
    base_date = timezone.now().date()
    room.paid_until = base_date
    room.save(update_fields=["paid_until"])

    payment = Payment.objects.create(
        user=landlord,
        room=room,
        amount="1.00",
        currency="GBP",
        status="created",
    )

    # Patch Stripe event parsing to always return the same completed event for this payment
    import propertylist_app.api.views as api_views

    def fake_construct_event(payload, sig_header, secret):
        return {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "payment_intent": "pi_test_123",
                    "metadata": {
                        "payment_id": str(payment.id),
                        "room_id": str(room.id),
                        "user_id": str(landlord.id),
                    },
                }
            },
        }

    monkeypatch.setattr(api_views.stripe.Webhook, "construct_event", fake_construct_event)

    client = APIClient()

    # Call webhook twice (simulating Stripe retry)
    res1 = client.post(
        "/api/payments/webhook/",
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="testsig",
    )
    res2 = client.post(
        "/api/payments/webhook/",
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="testsig",
    )

    assert res1.status_code == 200
    assert res2.status_code == 200

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == "succeeded"

    # Must be +30 days only once, not doubled
    assert room.paid_until == base_date + timedelta(days=30)

    # Notification must be created once (not duplicated)
    assert (
        Notification.objects.filter(user=landlord, title="Payment confirmed").count() == 1
    )
