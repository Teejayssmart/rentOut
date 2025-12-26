import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
import propertylist_app.api.views as views_mod



@pytest.mark.django_db
def test_setup_intent_creates_customer_if_missing_and_returns_client_secret(monkeypatch):
    User = get_user_model()
    user = User.objects.create_user(
        username="u1",
        email="u1@test.com",
        password="pass12345"
    )

    client = APIClient()
    client.force_authenticate(user=user)


    # mock Stripe Customer.create
    class DummyCustomer:
        id = "cus_test_123"

    def fake_customer_create(**kwargs):
        return DummyCustomer()

    monkeypatch.setattr(views_mod.stripe.Customer, "create", fake_customer_create)

    # mock Stripe SetupIntent.create
    class DummySetupIntent:
        client_secret = "seti_secret_456"

    def fake_setup_intent_create(**kwargs):
        return DummySetupIntent()

    monkeypatch.setattr(views_mod.stripe.SetupIntent, "create", fake_setup_intent_create)

    url = reverse("api:payments-setup-intent")
    r = client.post(url, {}, format="json")

    assert r.status_code == 200, r.content
    assert r.data.get("clientSecret") == "seti_secret_456"
    assert "publishableKey" in r.data  # can be empty in tests depending on settings


@pytest.mark.django_db
def test_setup_intent_returns_401_when_not_authenticated():
    client = APIClient()
    url = reverse("api:payments-setup-intent")
    r = client.post(url, {}, format="json")
    assert r.status_code == 401
