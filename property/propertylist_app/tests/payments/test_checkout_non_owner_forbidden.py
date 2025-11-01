import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from propertylist_app.models import Room, RoomCategorie, Payment

# We don't need to hit Stripe in this test; ensure it's never called.
import propertylist_app.api.views as views_mod

User = get_user_model()


@pytest.mark.django_db
def test_checkout_non_owner_forbidden(monkeypatch):
    """
    A user who is NOT the owner of the room must receive 403
    and no Stripe session should be created.
    """
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    stranger = User.objects.create_user(username="stranger", password="pass123", email="s@x.com")

    cat = RoomCategorie.objects.create(name="Paid", active=True)
    room = Room.objects.create(
        title="My Listing",
        category=cat,
        price_per_month=800,
        property_owner=owner,
        status="active",
    )

    # If Stripe were called, this will explode the test.
    def should_not_call_stripe(**kwargs):
        raise AssertionError("Stripe Session.create MUST NOT be called for non-owner.")

    monkeypatch.setattr(views_mod.stripe.checkout.Session, "create", should_not_call_stripe)

    client = APIClient()
    client.force_authenticate(user=stranger)

    url = reverse("v1:payments-checkout-room", kwargs={"pk": room.pk})
    r = client.post(url, {}, format="json")

    assert r.status_code == 403, r.content
    # Ensure no Payment row got created for this room/user combo
    assert not Payment.objects.filter(room=room, user=stranger).exists()
