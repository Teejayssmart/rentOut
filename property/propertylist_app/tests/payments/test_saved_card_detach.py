import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
import propertylist_app.api.views as views_mod
from propertylist_app.models import UserProfile


@pytest.mark.django_db
def test_detach_saved_card_success(monkeypatch):
    User = get_user_model()
    user = User.objects.create_user(username="u1", email="u1@test.com", password="pass12345")
    UserProfile.objects.create(user=user, stripe_customer_id="cus_test_123")

    client = APIClient()
    client.force_authenticate(user=user)

    called = {"pm_id": None}

    def fake_detach(pm_id):
        called["pm_id"] = pm_id
        return {}

    monkeypatch.setattr(views_mod.stripe.PaymentMethod, "detach", fake_detach)

    url = reverse("api:payments-saved-card-detach", kwargs={"pm_id": "pm_test_999"})
    r = client.post(url, {}, format="json")

    assert r.status_code == 200, r.content
    assert r.data["detail"] == "Card removed."
    assert called["pm_id"] == "pm_test_999"


@pytest.mark.django_db
def test_detach_saved_card_400_when_no_customer():
    User = get_user_model()
    user = User.objects.create_user(username="u2", email="u2@test.com", password="pass12345")
    UserProfile.objects.create(user=user, stripe_customer_id="")

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("api:payments-saved-card-detach", kwargs={"pm_id": "pm_test_111"})
    r = client.post(url, {}, format="json")

    assert r.status_code == 400
    assert "No Stripe customer" in r.data["detail"]


@pytest.mark.django_db
def test_detach_saved_card_401_when_not_authenticated():
    client = APIClient()
    url = reverse("api:payments-saved-card-detach", kwargs={"pm_id": "pm_test_222"})
    r = client.post(url, {}, format="json")
    assert r.status_code == 401
