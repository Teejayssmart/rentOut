import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from django.contrib.auth.models import User
from propertylist_app.models import Room, RoomCategorie, Payment

# Import the same module your view imports 'stripe' from
import propertylist_app.api.views as views_mod


@pytest.mark.django_db
def test_checkout_creates_session_for_owner_room(monkeypatch):
    """
    Owner requests a checkout session for their room:
      - returns 200 with {"checkout_url", "session_id"}
      - creates a Payment(row) with status="created" and links the Session id
    """

    # Arrange: owner + room
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    cat = RoomCategorie.objects.create(name="Paid", active=True)
    room = Room.objects.create(
        title="My Listing",
        category=cat,
        price_per_month=800,
        property_owner=owner,
    )

    # Fake Stripe Customer + Session objects
    class FakeCustomer:
        id = "cus_test_123"

    class FakeSession:
        id = "cs_test_456"
        url = "https://stripe.test/cs_test_456"

    def fake_customer_create(**kwargs):
        return FakeCustomer()

    def fake_session_create(**kwargs):
        assert kwargs.get("mode") == "payment"
        assert "metadata" in kwargs
        return FakeSession()

    # Patch BOTH Stripe calls used in the view
    monkeypatch.setattr(views_mod.stripe.Customer, "create", fake_customer_create)
    monkeypatch.setattr(views_mod.stripe.checkout.Session, "create", fake_session_create)


    

    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("v1:payments-checkout-room", kwargs={"pk": room.pk})

    # Act
    r = client.post(url, {}, format="json")

    # Assert HTTP + payload
    assert r.status_code == 200, r.content
    assert r.data.get("session_id") == "cs_test_456"
    assert r.data.get("checkout_url") is not None

    # Assert DB side-effects
    p = Payment.objects.get(room=room)
    assert p.user == owner
    assert p.amount == 1.00
    assert p.currency == "GBP"
    assert p.status == "created"
    assert p.stripe_checkout_session_id == "cs_test_456"
