import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from propertylist_app.models import Payment, UserProfile, Room


@pytest.mark.django_db
def test_transaction_detail_requires_authentication():
    client = APIClient()
    url = reverse("api:payments-transaction-detail", kwargs={"pk": 1})
    r = client.get(url)
    assert r.status_code == 401


@pytest.mark.django_db
def test_user_can_view_own_transaction_detail():
    User = get_user_model()
    user = User.objects.create_user(username="u1", password="pass12345")
    UserProfile.objects.create(user=user, stripe_customer_id="cus_1")

    room = Room.objects.create(title="My Room", property_owner=user, price_per_month=500)

    payment = Payment.objects.create(
        user=user,
        room=room,
        amount=100,
        currency="GBP",
        status="completed",
        stripe_payment_intent_id="pi_own",
        stripe_checkout_session_id="cs_test_1",
    )

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("api:payments-transaction-detail", kwargs={"pk": payment.pk})
    r = client.get(url)

    assert r.status_code == 200, r.content
    assert r.data["transaction_id"] == "pi_own"
    assert r.data["listing_title"] == "My Room"


@pytest.mark.django_db
def test_user_cannot_view_someone_else_transaction():
    User = get_user_model()
    user1 = User.objects.create_user(username="u1", password="pass12345")
    user2 = User.objects.create_user(username="u2", password="pass12345")

    UserProfile.objects.create(user=user1, stripe_customer_id="cus_1")
    UserProfile.objects.create(user=user2, stripe_customer_id="cus_2")

    room = Room.objects.create(title="Other Room", property_owner=user2, price_per_month=600)

    payment = Payment.objects.create(
        user=user2,
        room=room,
        amount=200,
        currency="GBP",
        status="completed",
        stripe_payment_intent_id="pi_other",
        stripe_checkout_session_id="cs_test_2",
    )

    client = APIClient()
    client.force_authenticate(user=user1)

    url = reverse("api:payments-transaction-detail", kwargs={"pk": payment.pk})
    r = client.get(url)

    # because queryset is restricted to request.user payments, this will be 404
    assert r.status_code == 404
