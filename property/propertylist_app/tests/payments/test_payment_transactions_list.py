import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from propertylist_app.models import Payment, UserProfile, Room, RoomCategorie



def make_category(name="Payment List Category"):
    return RoomCategorie.objects.create(name=name, active=True)


@pytest.mark.django_db
def test_payments_transactions_list_requires_authentication():
    client = APIClient()
    url = reverse("api:payments-transactions")
    response = client.get(url)
    assert response.status_code == 401


@pytest.mark.django_db
def test_user_sees_only_their_own_payments():
    User = get_user_model()

    user1 = User.objects.create_user(username="user1", password="pass12345")
    user2 = User.objects.create_user(username="user2", password="pass12345")

    UserProfile.objects.create(user=user1, stripe_customer_id="cus_1")
    UserProfile.objects.create(user=user2, stripe_customer_id="cus_2")

    cat1 = make_category("Payment List Category 1")
    cat2 = make_category("Payment List Category 2")

    room1 = Room.objects.create(
        title="Room One",
        description="Payment list room one",
        price_per_month=500,
        location="SO14",
        category=cat1,
        property_owner=user1,
    )

    room2 = Room.objects.create(
        title="Room Two",
        description="Payment list room two",
        price_per_month=600,
        location="SO15",
        category=cat2,
        property_owner=user2,
    )



    Payment.objects.create(
        user=user1,
        room=room1,
        amount=100,
        currency="GBP",
        status="completed",
        stripe_payment_intent_id="pi_user1",
    )

    Payment.objects.create(
        user=user2,
        room=room2,
        amount=200,
        currency="GBP",
        status="completed",
        stripe_payment_intent_id="pi_user2",
    )

    client = APIClient()
    client.force_authenticate(user=user1)

    url = reverse("api:payments-transactions")
    response = client.get(url)

    assert response.status_code == 200
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["transaction_id"] == "pi_user1"


@pytest.mark.django_db
def test_search_by_listing_title():
    User = get_user_model()
    user = User.objects.create_user(username="user", password="pass12345")
    UserProfile.objects.create(user=user, stripe_customer_id="cus_test")

    cat = make_category("Payment Search Category")

    room = Room.objects.create(
        title="Cosy London Room",
        description="Payment search room",
        price_per_month=700,
        location="London",
        category=cat,
        property_owner=user,
    )



    Payment.objects.create(
        user=user,
        room=room,
        amount=150,
        currency="GBP",
        status="completed",
        stripe_payment_intent_id="pi_123",
    )

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("api:payments-transactions") + "?q=London"
    response = client.get(url)

    assert response.status_code == 200
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["listing_title"] == "Cosy London Room"


@pytest.mark.django_db
def test_date_filter_last_7_days():
    User = get_user_model()
    user = User.objects.create_user(username="user", password="pass12345")
    UserProfile.objects.create(user=user, stripe_customer_id="cus_test")

    cat = make_category("Payment Date Filter Category")

    room = Room.objects.create(
        title="Room",
        description="Payment date filter room",
        price_per_month=800,
        location="SO16",
        category=cat,
        property_owner=user,
    )



    recent_payment = Payment.objects.create(
    user=user,
    room=room,
    amount=100,
    currency="GBP",
    status="completed",
    stripe_payment_intent_id="pi_recent",
    )

    old_payment = Payment.objects.create(
        user=user,
        room=room,
        amount=100,
        currency="GBP",
        status="completed",
        stripe_payment_intent_id="pi_old",
    )

    # Force the timestamps (works even if created_at is auto_now_add)
    Payment.objects.filter(pk=recent_payment.pk).update(created_at=timezone.now() - timedelta(days=2))
    Payment.objects.filter(pk=old_payment.pk).update(created_at=timezone.now() - timedelta(days=30))
    

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("api:payments-transactions") + "?range=last_7_days"
    response = client.get(url)

    assert response.status_code == 200
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["transaction_id"] == "pi_recent"
