import uuid
import pytest
from django.urls import reverse

from propertylist_app.api import views as api_views
from propertylist_app.models import Payment, Room, RoomCategorie, WebhookReceipt


@pytest.mark.django_db
def test_stripe_webhook_is_idempotent_on_duplicate_event_id(monkeypatch, api_client, user_factory):
    # Reason: Stripe can retry the same event. We must not finalise twice.

    # Arrange: landlord + room + payment in a non-succeeded state
    landlord = user_factory(username="landlord_wh", email="landlord_wh@example.com", password="pass123")
    cat = RoomCategorie.objects.create(name="Test", active=True)

    room = Room.objects.create(
        title="Room for webhook",
        description="x",
        price_per_month=500,
        location="SW1A 1AA",
        category=cat,
        property_owner=landlord,
        status="active",
        is_deleted=False,
        paid_until=None,
    )

    payment = Payment.objects.create(
        user=landlord,
        room=room,
        provider=Payment.Provider.STRIPE,
        amount="1.00",
        currency="GBP",
        status=Payment.Status.REQUIRES_PAYMENT,
        stripe_checkout_session_id="cs_test_dummy",
        stripe_payment_intent_id="",
    )

    # Build a fake Stripe event returned by stripe.Webhook.construct_event
    # IMPORTANT: event_id must be unique per test run (suite-safe).
    event_id = f"evt_test_{uuid.uuid4().hex}"

    fake_event = {
        "id": event_id,
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

    def _fake_construct_event(payload=None, sig_header=None, secret=None):
        return fake_event

    # Patch the exact stripe reference used inside propertylist_app.api.views
    monkeypatch.setattr(api_views.stripe.Webhook, "construct_event", _fake_construct_event)

    url = reverse("v1:stripe-webhook")

    # Act: first delivery
    res1 = api_client.post(
        url,
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=fake",
    )
    assert res1.status_code == 200

    room.refresh_from_db()
    payment.refresh_from_db()
    first_paid_until = room.paid_until

    assert payment.status == Payment.Status.SUCCEEDED
    assert first_paid_until is not None

    # Act: duplicate delivery (same event id)
    res2 = api_client.post(
        url,
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=fake",
    )
    assert res2.status_code == 200

    room.refresh_from_db()
    payment.refresh_from_db()

    # Assert: no double state change
    assert payment.status == Payment.Status.SUCCEEDED
    assert room.paid_until == first_paid_until

    # Assert: receipt stored once due to unique event_id
    assert WebhookReceipt.objects.filter(event_id=event_id).count() == 1