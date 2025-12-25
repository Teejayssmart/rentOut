import pytest
from unittest.mock import patch
from django.utils import timezone

from rest_framework.test import APIClient

from propertylist_app.models import Notification, UserProfile, Payment, Room


pytestmark = pytest.mark.django_db


def test_stripe_webhook_creates_payment_confirmation_notification_when_enabled(user_factory, room_factory):
    client = APIClient()

    user = user_factory()
    room = room_factory(property_owner=user)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_confirmations = True
    profile.save(update_fields=["notify_confirmations"])

    payment = Payment.objects.create(
        user=user,
        room=room,
        amount=10,
        currency="GBP",
        status="created",
    )

    fake_event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "payment_intent": "pi_test_123",
                "metadata": {"payment_id": str(payment.id)},
            }
        },
    }

    with patch("propertylist_app.api.views.stripe.Webhook.construct_event", return_value=fake_event):
        res = client.post(
            "/api/payments/webhook/",
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_sig",
        )

    assert res.status_code == 200

    assert Notification.objects.filter(
        user=user,
        type="confirmation",
        title="Payment confirmed",
    ).exists()


def test_stripe_webhook_does_not_create_payment_confirmation_notification_when_disabled(user_factory, room_factory):
    client = APIClient()

    user = user_factory()
    room = room_factory(property_owner=user)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.notify_confirmations = False
    profile.save(update_fields=["notify_confirmations"])

    payment = Payment.objects.create(
        user=user,
        room=room,
        amount=10,
        currency="GBP",
        status="created",
    )

    fake_event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "payment_intent": "pi_test_123",
                "metadata": {"payment_id": str(payment.id)},
            }
        },
    }

    with patch("propertylist_app.api.views.stripe.Webhook.construct_event", return_value=fake_event):
        res = client.post(
            "/api/payments/webhook/",
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_sig",
        )

    assert res.status_code == 200

    assert not Notification.objects.filter(
        user=user,
        type="confirmation",
        title="Payment confirmed",
    ).exists()
