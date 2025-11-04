import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth.models import User
from propertylist_app.models import Room, RoomCategorie, Payment


@pytest.mark.django_db
def test_cancel_keeps_state_unchanged():
    """
    Cancelling a checkout session should not accidentally mark the payment as succeeded
    or change the room visibility/state.
    """
    # Arrange
    owner = User.objects.create_user(username="owner2", password="pass123", email="o2@example.com")
    cat = RoomCategorie.objects.create(name="Cancelable", active=True)
    room = Room.objects.create(
        title="Cancelable Room",
        category=cat,
        price_per_month=750,
        property_owner=owner,
        status="active",
    )
    payment = Payment.objects.create(
        user=owner, room=room, amount=1.00, currency="GBP", status="created"
    )

    client = APIClient()

    # Act: call the cancel endpoint (simulates user cancelling checkout)
    cancel_url = reverse("v1:payments-cancel")
    r = client.get(cancel_url, {"payment_id": str(payment.id)})

    # Assert HTTP 200 response
    assert r.status_code == 200, r.content
    data = r.json()
    assert "canceled" in data["detail"].lower()

    # Refresh from DB
    payment.refresh_from_db()
    room.refresh_from_db()

    # Assert: payment was canceled, not marked succeeded
    assert payment.status == "canceled"
    # Room stays active (no hidden or deleted change)
    assert room.status == "active"
