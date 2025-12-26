import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

import propertylist_app.api.views as views_mod
from propertylist_app.models import UserProfile


@pytest.mark.django_db
def test_set_default_card_success(monkeypatch):
    User = get_user_model()
    user = User.objects.create_user(username="u1", email="u1@test.com", password="pass12345")
    UserProfile.objects.create(user=user, stripe_customer_id="cus_test_123")

    client = APIClient()
    client.force_authenticate(user=user)

    called = {"customer_id": None, "default_pm": None}

    def fake_customer_modify(customer_id, **kwargs):
        called["customer_id"] = customer_id
        called["default_pm"] = kwargs.get("invoice_settings", {}).get("default_payment_method")
        return {}

    monkeypatch.setattr(views_mod.stripe.Customer, "modify", fake_customer_modify)

    url = reverse("api:payments-saved-card-set-default", kwargs={"pm_id": "pm_test_999"})
    r = client.post(url, {}, format="json")

    assert r.status_code == 200, r.content
    assert r.data["detail"] == "Default card updated."
    assert called["customer_id"] == "cus_test_123"
    assert called["default_pm"] == "pm_test_999"


@pytest.mark.django_db
def test_set_default_card_400_when_no_customer():
    User = get_user_model()
    user = User.objects.create_user(username="u2", email="u2@test.com", password="pass12345")
    UserProfile.objects.create(user=user, stripe_customer_id="")

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("api:payments-saved-card-set-default", kwargs={"pm_id": "pm_test_111"})
    r = client.post(url, {}, format="json")

    assert r.status_code == 400
    assert "No Stripe customer" in r.data["detail"]


@pytest.mark.django_db
def test_set_default_card_401_when_not_authenticated():
    client = APIClient()
    url = reverse("api:payments-saved-card-set-default", kwargs={"pm_id": "pm_test_222"})
    r = client.post(url, {}, format="json")
    assert r.status_code == 401
