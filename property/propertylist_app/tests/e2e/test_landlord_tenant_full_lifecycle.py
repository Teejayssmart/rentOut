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


@override_settings(DEBUG_PROPAGATE_EXCEPTIONS=True)
def test_e2e_landlord_tenant_full_lifecycle(monkeypatch, user_factory, room_factory, tmp_path):
    """
    End-to-end journey across modules:

    landlord: room exists -> upload photo -> pay (checkout) -> webhook finalises (paid_until extended) -> notification
    tenant: booking preflight -> create booking -> booking notification -> start thread -> send message
    """

    # Force file uploads to go to a writable temp folder during tests
    # Reason: prevents 500s caused by MEDIA_ROOT pointing to a production path (e.g. /var/data) or unwritable location
    with override_settings(MEDIA_ROOT=str(tmp_path)):

        # -----------------------------
        # arrange users + room
        # -----------------------------
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

        # -----------------------------
        # capture tenancy notification task calls
        # -----------------------------
        tenancy_task_calls = []

        def fake_delay(tenancy_id, event):
            tenancy_task_calls.append((tenancy_id, event))
            return None

        import propertylist_app.tasks as tasks

        monkeypatch.setattr(tasks.task_send_tenancy_notification, "delay", fake_delay)

        # -----------------------------
        # landlord uploads photo
        # endpoint: rooms/<pk>/photos/
        # -----------------------------
        # Make upload deterministic in tests:
        # Reason: the endpoint uses moderation + validators that may raise in test env
        # (and then your global error envelope returns a generic 500).
        import propertylist_app.api.views as api_views

        monkeypatch.setattr(api_views, "should_auto_approve_upload", lambda _f: True)

        # These two are called inside the upload view; if they raise a non-DjangoValidationError
        # the view would 500. We no-op them for this e2e flow test.
        if hasattr(api_views, "validate_listing_photos"):
            monkeypatch.setattr(api_views, "validate_listing_photos", lambda files, max_mb=5: None)
        if hasattr(api_views, "assert_no_duplicate_files"):
            monkeypatch.setattr(api_views, "assert_no_duplicate_files", lambda files: None)

        # real 1x1 PNG so ImageField/Pillow validation cannot crash and return 500
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

        # -----------------------------
        # landlord starts checkout
        # endpoint: payments/checkout/rooms/<pk>/
        # -----------------------------
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

        # handle either raw or enveloped success payload
        payload = res.data.get("data") if isinstance(res.data, dict) and res.data.get("ok") is True else res.data
        assert payload.get("session_id") == "cs_test_123"
        assert payload.get("checkout_url") is not None

        payment = Payment.objects.get(room=room, user=landlord)
        assert payment.status == "created"

        # -----------------------------
        # webhook finalises payment
        # endpoint: payments/webhook/
        # -----------------------------
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

        # -----------------------------
        # tenant booking pre-flight (optional but part of flow)
        # endpoint: bookings/create/
        # -----------------------------
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

        # -----------------------------
        # tenant creates booking
        # endpoint: bookings/
        # -----------------------------
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

        # -----------------------------
        # tenant starts thread from room and sends a message
        # endpoint: rooms/<room_id>/start-thread/
        # endpoint: messages/threads/<thread_id>/messages/
        # -----------------------------
        res = tenant_client.post(
            f"/api/v1/rooms/{room.id}/start-thread/",
            data={"body": "Hi, is the room still available?"},
            format="json",
        )
        assert res.status_code in (200, 201), getattr(res, "data", res.content)

        payload = res.data.get("data") if isinstance(res.data, dict) and res.data.get("ok") is True else res.data
        thread_id = payload.get("id") or payload.get("thread_id")
        assert thread_id, payload

        res = tenant_client.post(
            f"/api/v1/messages/threads/{thread_id}/messages/",
            data={"body": "Can I book a viewing this week?"},
            format="json",
        )
        assert res.status_code in (200, 201), getattr(res, "data", res.content)

        # -----------------------------
        # tenancy propose (tenant proposes to landlord)
        # endpoint: /api/v1/tenancies/propose/
        # -----------------------------
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

        payload = res.data.get("data") if isinstance(res.data, dict) and res.data.get("ok") is True else res.data
        tenancy_id = payload["id"]
        assert (tenancy_id, "proposed") in tenancy_task_calls

        tenancy = Tenancy.objects.get(id=tenancy_id)
        assert tenancy.room_id == room.id
        assert tenancy.tenant_id == tenant.id
        assert tenancy.landlord_id == landlord.id
        assert tenancy.status in ("proposed", "confirmed", "active")
        assert tenancy.tenant_confirmed_at is not None

        # -----------------------------
        # landlord confirms
        # endpoint: /api/v1/tenancies/<id>/respond/
        # -----------------------------
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

        # open review window for test
        tenancy.review_open_at = timezone.now() - timedelta(days=1)
        tenancy.review_deadline_at = timezone.now() + timedelta(days=30)
        tenancy.save(update_fields=["review_open_at", "review_deadline_at"])

        # -----------------------------
        # tenant submits tenancy review
        # endpoint: /api/v1/tenancies/<id>/reviews/
        # -----------------------------
        res = tenant_client.post(
            f"/api/v1/tenancies/{tenancy_id}/reviews/",
            data={"overall_rating": 5, "notes": "All good."},
            format="json",
        )
        assert res.status_code == 201, getattr(res, "data", res.content)

        review = Review.objects.filter(tenancy_id=tenancy_id, reviewer_id=tenant.id).first()
        assert review is not None
        assert review.reviewee_id == landlord.id
