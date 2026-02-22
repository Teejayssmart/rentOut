import pytest
from datetime import timedelta

from django.utils import timezone
from django.urls import reverse

from propertylist_app.api import views as api_views
from propertylist_app.models import Payment, Room, RoomCategorie


@pytest.mark.django_db
def test_payment_reflects_in_room_state(monkeypatch, api_client, user_factory):
    """
    E4: Confirm payment status updates are reflected in room state for UI.

    What this test proves:
    - When Stripe webhook delivers checkout.session.completed
      -> Payment.status becomes SUCCEEDED
      -> Room.paid_until is extended
      -> Room detail payload reflects paid_until and listing_state="active"
    """

    # -----------------------------
    # Arrange: landlord + room + payment (unpaid)
    # -----------------------------
    landlord = user_factory(
        username="landlord_e4",
        email="landlord_e4@example.com",
        password="pass123",
    )

    cat = RoomCategorie.objects.create(name="Test", active=True)

    room = Room.objects.create(
        title="Room for E4",
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

    # Webhook fake event returned by stripe.Webhook.construct_event
    fake_event = {
        "id": "evt_e4_room_state_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "payment_intent": "pi_e4_123",
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

    # Reason: keep patch local to the module used by the webhook view
    monkeypatch.setattr(api_views.stripe.Webhook, "construct_event", _fake_construct_event)

    # Auth for room + transactions endpoints (webhook is AllowAny)
    api_client.force_authenticate(user=landlord)

    # -----------------------------
    # Assert pre-state (before webhook)
    # -----------------------------
    room.refresh_from_db()
    payment.refresh_from_db()

    assert room.paid_until is None
    assert payment.status == Payment.Status.REQUIRES_PAYMENT

    # -----------------------------
    # Act: deliver webhook
    # -----------------------------
    webhook_url = reverse("v1:stripe-webhook")
    res = api_client.post(
        webhook_url,
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=fake",
    )
    assert res.status_code == 200

    # -----------------------------
    # Assert DB state updated
    # -----------------------------
    room.refresh_from_db()
    payment.refresh_from_db()

    assert payment.status == Payment.Status.SUCCEEDED
    assert room.paid_until is not None

    # Sanity check: paid_until should be about +30 days from "today"
    # (Allowing a 1-day tolerance avoids timezone edge flakiness.)
    today = timezone.now().date()
    assert room.paid_until >= today + timedelta(days=29)

    # -----------------------------
    # Assert room detail response reflects payment state (UI-facing)
    # -----------------------------
    room_detail_url = f"/api/v1/rooms/{room.id}/"
    room_res = api_client.get(room_detail_url)
    assert room_res.status_code == 200

    # Reason: some endpoints are A3-enveloped, some return raw serializer data.
    payload = room_res.data.get("data") if isinstance(room_res.data, dict) and "data" in room_res.data and room_res.data.get("ok") is True else room_res.data

    assert str(payload.get("paid_until")) == str(room.paid_until)
    assert payload.get("listing_state") == "active"

    # -----------------------------
    # Assert transactions endpoint reflects succeeded payment (optional UI screen)
    # -----------------------------
    tx_url = "/api/v1/payments/transactions/"
    tx_res = api_client.get(tx_url)
    assert tx_res.status_code == 200

    tx_payload = tx_res.data.get("data") if isinstance(tx_res.data, dict) and tx_res.data.get("ok") is True else tx_res.data

    # tx_payload can be either a list, or a paginated dict with "results"
    if isinstance(tx_payload, dict) and "results" in tx_payload:
        items = tx_payload["results"]
    else:
        items = tx_payload.get("results") if isinstance(tx_payload, dict) else tx_payload

    assert any(str(item.get("status")) == "succeeded" for item in items)