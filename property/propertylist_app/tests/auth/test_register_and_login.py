import pytest
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_register_then_login_success_and_bad_password():
    """
    Real life: a user signs up, then logs in from the app.
    We assert registration returns minimal safe profile,
    login returns JWT tokens, and a bad password is rejected.
    """
    client = APIClient()

    # --- Register ---
    url_reg = reverse("v1:auth-register")
    payload = {"username": "alice", "email": "alice@example.com", "password": "pass12345"}
    r = client.post(url_reg, payload, format="json")
    assert r.status_code == 201, r.data
    assert {"id", "username", "email"} <= set(r.data.keys())
    assert r.data["username"] == "alice"

    # sanity: user actually exists
    assert User.objects.filter(username="alice").exists()

    # --- Login (ok) ---
    url_login = reverse("v1:auth-login")
    r2 = client.post(url_login, {"username": "alice", "password": "pass12345"}, format="json")
    assert r2.status_code == 200, r2.data
    # Your login view returns both tokens
    assert "access" in r2.data and "refresh" in r2.data

    # --- Login (bad password) ---
    r3 = client.post(url_login, {"username": "alice", "password": "wrong"}, format="json")
    # Your view returns 400 on invalid credentials
    assert r3.status_code == 400, r3.data
