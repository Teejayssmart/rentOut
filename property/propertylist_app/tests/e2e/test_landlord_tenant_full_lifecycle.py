import base64
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Notification, Payment, Review, Tenancy

pytestmark = pytest.mark.django_db


def _auth(client: APIClient, user):
    client.force_authenticate(user=user)
    return client


def _unwrap(response):
    if isinstance(response.data, dict) and response.data.get("ok") is True:
        return response.data.get("data", {})
    return response.data


@override_settings(DEBUG_PROPAGATE_EXCEPTIONS=True)
def test_e2e_landlord_tenant_full_lifecycle(monkeypatch, user_factory, room_factory, tmp_path):
    """
    End-to-end journey across modules:

    landlord: room exists -> upload photo -> pay -> webhook finalises -> notification
    tenant: booking -> message thread -> tenancy proposal -> confirmation -> tenancy review
    """

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        landlord = user_factory(username="landlord1", email="landlord1@test.com", role="landlord")
        tenant = user_factory(username="tenant1", email="tenant1@test.com", role="seeker")

        room = room_factory(
            property_owner=landlord,
            title="Nice double room",
            price_per_month="500.00",
            location="SW1A 1AA",
            property_type="flat",
        )

        landlord_client = _auth(APIClient(), landlord)
        tenant_client = _auth(APIClient(), tenant)

        tenancy_task_calls = []

        def fake_delay(tenancy_id, event):
            tenancy_task_calls.append((tenancy_id, event))
            return None

        import propertylist_app.tasks as tasks

        monkeypatch.setattr(tasks.task_send_tenancy_notification, "delay", fake_delay)

        import propertylist_app.api.views as api_views
        import propertylist_app.api.views.rooms as room_views

        monkeypatch.setattr(room_views, "should_auto_approve_upload", lambda _f: True)

        if hasattr(room_views, "validate_listing_photos"):
            monkeypatch.setattr(room_views, "validate_listing_photos", lambda files, max_mb=5: None)
        if hasattr(room_views, "assert_no_duplicate_files"):
            monkeypatch.setattr(room_views, "assert_no_duplicate_files", lambda files: None)

        png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
            "/w8AAn8B9pWZ8QAAAABJRU5ErkJggg=="
        )
        fake_png = base64.b64decode(png_b64)
        upload = SimpleUploadedFile("room.png", fake_png, content_type="image/png")

        res = landlord_client.post(
            f"/api/v1/rooms/{room.id}/photos/",
            data={"image": upload},
            format="multipart",
        )
        assert res.status_code in (200, 201), getattr(res, "data", res.content)

        class _FakeStripeObj:
            def __init__(self, _id):
                self.id = _id
                self.url = f"https://stripe.test/{_id}"

        def fake_customer_create(*args, **kwargs):
            return _FakeStripeObj("cus_test_123")

        def fake_session_create(*args, **kwargs):
            return _FakeStripeObj("cs_test_123")

        monkeypatch.setattr(api_views.stripe.Customer, "create", fake_customer_create)
        monkeypatch.setattr(api_views.stripe.checkout.Session, "create", fake_session_create)

        res = landlord_client.post(
            f"/api/v1/payments/checkout/rooms/{room.id}/",
            data={},
            format="json",
        )
        assert res.status_code == 200, getattr(res, "data", res.content)

        payload = _unwrap(res)
        assert payload.get("session_id") == "cs_test_123"
        assert payload.get("checkout_url") is not None

        payment = Payment.objects.get(room=room, user=landlord)
        assert payment.status == "created"

        def fake_construct_event(*, payload, sig_header, secret, **kwargs):
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

        before_paid_until = room.paid_until
        res = landlord_client.post(
            "/api/v1/payments/webhook/",
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="testsig",
        )
        assert res.status_code == 200, getattr(res, "data", res.content)

        room.refresh_from_db()
        payment.refresh_from_db()

        assert payment.status == "succeeded"
        assert room.paid_until is not None
        if before_paid_until:
            assert room.paid_until >= before_paid_until

        assert Notification.objects.filter(user=landlord, title="Payment confirmed").exists()

        start_dt = timezone.now() - timedelta(days=2)
        end_dt = timezone.now() - timedelta(days=2, hours=-1)

        res = tenant_client.post(
            "/api/v1/bookings/create/",
            data={
                "room": room.id,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="idem-key-1",
        )
        assert res.status_code == 200, getattr(res, "data", res.content)

        res = tenant_client.post(
            "/api/v1/bookings/",
            data={
                "room": room.id,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
            },
            format="json",
        )
        assert res.status_code in (200, 201), getattr(res, "data", res.content)

        assert Notification.objects.filter(user=tenant, title="Booking confirmed").exists()

        res = tenant_client.post(
            f"/api/v1/rooms/{room.id}/start-thread/",
            data={"body": "Hi, is the room still available?"},
            format="json",
        )
        assert res.status_code in (200, 201), getattr(res, "data", res.content)

        payload = _unwrap(res)
        thread_id = payload.get("id") or payload.get("thread_id")
        assert thread_id, payload

        res = tenant_client.post(
            f"/api/v1/messages/threads/{thread_id}/messages/",
            data={"body": "Can I book a viewing this week?"},
            format="json",
        )
        assert res.status_code in (200, 201), getattr(res, "data", res.content)

        move_in = timezone.localdate() + timedelta(days=1)
        res = tenant_client.post(
            "/api/v1/tenancies/propose/",
            data={
                "room_id": room.id,
                "counterparty_user_id": landlord.id,
                "move_in_date": str(move_in),
                "duration_months": 1,
            },
            format="json",
        )
        assert res.status_code == 201, getattr(res, "data", res.content)

        payload = _unwrap(res)
        tenancy_id = payload["id"]
        assert (tenancy_id, "proposed") in tenancy_task_calls

        tenancy = Tenancy.objects.get(id=tenancy_id)
        assert tenancy.room_id == room.id
        assert tenancy.tenant_id == tenant.id
        assert tenancy.landlord_id == landlord.id
        assert tenancy.status in ("proposed", "confirmed", "active")
        assert tenancy.tenant_confirmed_at is not None

        res = landlord_client.post(
            f"/api/v1/tenancies/{tenancy_id}/respond/",
            data={"action": "confirm"},
            format="json",
        )
        assert res.status_code == 200, getattr(res, "data", res.content)
        assert (tenancy_id, "confirmed") in tenancy_task_calls

        tenancy.refresh_from_db()
        assert tenancy.landlord_confirmed_at is not None
        assert tenancy.status in ("confirmed", "active")
        assert tenancy.review_open_at is not None
        assert tenancy.review_deadline_at is not None

        tenancy.review_open_at = timezone.now() - timedelta(days=1)
        tenancy.review_deadline_at = timezone.now() + timedelta(days=30)
        tenancy.save(update_fields=["review_open_at", "review_deadline_at"])

        # Reviews are created through the central review-create endpoint.
        # Booking/viewing routes do not create reviews.
        res = tenant_client.post(
            "/api/v1/reviews/create/",
            data={
                "tenancy_id": tenancy_id,
                "overall_rating": 5,
                "notes": "All good.",
            },
            format="json",
        )
        assert res.status_code == 201, getattr(res, "data", res.content)

        review = Review.objects.filter(tenancy_id=tenancy_id, reviewer_id=tenant.id).first()
        assert review is not None
        assert review.reviewee_id == landlord.id
        assert int(review.overall_rating) == 5