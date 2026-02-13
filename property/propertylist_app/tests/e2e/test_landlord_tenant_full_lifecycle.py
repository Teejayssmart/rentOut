import json
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, Payment, Notification
from datetime import timedelta, date

from propertylist_app.models import Room, Payment, Notification, Tenancy, Review


pytestmark = pytest.mark.django_db


def _auth(client: APIClient, user):
    client.force_authenticate(user=user)
    return client


def test_e2e_landlord_tenant_full_lifecycle(monkeypatch, user_factory, room_factory):

    """
    End-to-end journey across modules:

    landlord: room exists -> upload photo -> pay (checkout) -> webhook finalises (paid_until extended) -> notification
    tenant: booking preflight -> create booking -> booking notification -> start thread -> send message
    """

    # -----------------------------
    # arrange users + room
    # -----------------------------
    # arrange users + room (use your fixtures so required model fields are correct)
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
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    upload = SimpleUploadedFile("room.png", fake_png, content_type="image/png")

    res = landlord_client.post(
        f"/api/rooms/{room.id}/photos/",
        data={"image": upload},
        format="multipart",
    )
    assert res.status_code in (200, 201), res.data

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
        # must return something with .id (your view reads session.id)
        return _FakeStripeObj("cs_test_123")

    # patch stripe calls used inside CreateListingCheckoutSessionView
    import propertylist_app.api.views as api_views

    monkeypatch.setattr(api_views.stripe.Customer, "create", fake_customer_create)
    monkeypatch.setattr(api_views.stripe.checkout.Session, "create", fake_session_create)

    res = landlord_client.post(f"/api/payments/checkout/rooms/{room.id}/", data={}, format="json")
    assert res.status_code == 200, res.data
    assert res.data.get("session_id") == "cs_test_123"
    assert res.data.get("checkout_url") is not None


    payment = Payment.objects.get(room=room, user=landlord)
    assert payment.status == "created"

    # -----------------------------
    # webhook finalises payment
    # endpoint: payments/webhook/
    # stripe_webhook uses stripe.Webhook.construct_event(...)
    # -----------------------------
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

    before_paid_until = room.paid_until
    res = landlord_client.post(
        "/api/payments/webhook/",
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="testsig",
    )
    assert res.status_code == 200

    room.refresh_from_db()
    payment.refresh_from_db()

    assert payment.status == "succeeded"
    assert room.paid_until is not None
    if before_paid_until:
        assert room.paid_until >= before_paid_until

    assert Notification.objects.filter(user=landlord, title="Payment confirmed").exists()


    # -----------------------------
    # capture tenancy notification task calls
    # -----------------------------
    tenancy_task_calls = []

    def fake_delay(tenancy_id, event):
        tenancy_task_calls.append((tenancy_id, event))
        return None  # don't execute anything

    import propertylist_app.tasks as tasks
    monkeypatch.setattr(tasks.task_send_tenancy_notification, "delay", fake_delay)



    # -----------------------------
    # tenant booking pre-flight (optional but part of flow)
    # endpoint: bookings/create/
    # -----------------------------
    start_dt = timezone.now() - timedelta(days=2)
    end_dt = timezone.now() - timedelta(days=2, hours=-1)

    res = tenant_client.post(
        "/api/bookings/create/",
        data={
            "room": room.id,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="idem-key-1",
    )
    assert res.status_code == 200, res.data

    # -----------------------------
    # tenant creates booking
    # endpoint: bookings/
    # -----------------------------
    res = tenant_client.post(
        "/api/bookings/",
        data={
            "room": room.id,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
        },
        format="json",
    )
    assert res.status_code in (200, 201), res.data

    assert Notification.objects.filter(user=tenant, title="Booking confirmed").exists()

    # -----------------------------
    # tenant starts thread from room and sends a message
    # endpoint: rooms/<room_id>/start-thread/
    # endpoint: messages/threads/<thread_id>/messages/
    # -----------------------------
    res = tenant_client.post(
    f"/api/rooms/{room.id}/start-thread/",
    data={"body": "Hi, is the room still available?"},
    format="json",
    )

    assert res.status_code in (200, 201), res.data
    thread_id = res.data.get("id") or res.data.get("thread_id")
    assert thread_id, res.data

    res = tenant_client.post(
    f"/api/messages/threads/{thread_id}/messages/",
    data={"body": "Can I book a viewing this week?"},
    format="json",
    )

    assert res.status_code in (200, 201), res.data



    # -----------------------------
    # tenancy propose (tenant proposes to landlord)
    # endpoint: /api/tenancies/propose/
    # rules: tenant must have completed a viewing (we already booked in the past)
    # -----------------------------
    move_in = timezone.localdate() + timedelta(days=1)  # must not be in the past
    res = tenant_client.post(
        "/api/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": landlord.id,  # tenant must propose to landlord
            "move_in_date": str(move_in),
            "duration_months": 1,
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    tenancy_id = res.data["id"]
    assert (tenancy_id, "proposed") in tenancy_task_calls


    tenancy = Tenancy.objects.get(id=tenancy_id)
    assert tenancy.room_id == room.id
    assert tenancy.tenant_id == tenant.id
    assert tenancy.landlord_id == landlord.id
    assert tenancy.status in ("proposed", "confirmed", "active")

    # proposer auto-confirms their side
    assert tenancy.tenant_confirmed_at is not None

    # -----------------------------
    # landlord confirms
    # endpoint: /api/tenancies/<id>/respond/
    # -----------------------------
    res = landlord_client.post(
        f"/api/tenancies/{tenancy_id}/respond/",
        data={"action": "confirm"},
        format="json",
    )
    assert res.status_code == 200, res.data
    assert (tenancy_id, "confirmed") in tenancy_task_calls


    tenancy.refresh_from_db()
    assert tenancy.landlord_confirmed_at is not None

    # after both confirm, status becomes confirmed/active and schedule fields are set
    assert tenancy.status in ("confirmed", "active")
    assert tenancy.review_open_at is not None
    assert tenancy.review_deadline_at is not None

    # -----------------------------
    # open the review window for test purposes
    # (real rule is: end_date + 7 days, which is in the future for any move-in today)
    # so we set review_open_at to the past
    # -----------------------------
    tenancy.review_open_at = timezone.now() - timedelta(days=1)
    tenancy.review_deadline_at = timezone.now() + timedelta(days=30)
    tenancy.save(update_fields=["review_open_at", "review_deadline_at"])

    # -----------------------------
    # tenant submits tenancy review
    # endpoint: /api/tenancies/<id>/reviews/
    # uses ReviewCreateSerializer and requires tenancy_id + overall_rating (if no flags)
    # -----------------------------
    res = tenant_client.post(
        f"/api/tenancies/{tenancy_id}/reviews/",
        data={
            "overall_rating": 5,
            "notes": "All good.",
        },
        format="json",
    )
    assert res.status_code == 201, res.data

    # ensure review exists and is linked correctly
    review = Review.objects.filter(tenancy_id=tenancy_id, reviewer_id=tenant.id).first()
    assert review is not None
    assert review.reviewee_id == landlord.id

