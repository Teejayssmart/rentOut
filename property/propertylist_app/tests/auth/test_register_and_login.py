# property/propertylist_app/tests/auth/test_register_and_login.py

import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile


User = get_user_model()


@pytest.mark.django_db
def test_register_then_login_success_and_bad_password():
    """
    Real life: a user signs up, verifies email, then logs in from the app.
    We assert registration returns 201,
    login returns JWT tokens, and a bad password is rejected.
    """
    client = APIClient()

    # --- Register ---
    url_reg = reverse("v1:auth-register")
    payload = {
        "username": "alice",
        "email": "alice@example.com",
        "password": "Pass12345!",
        "role": "seeker",          # valid: "landlord", "seeker"
        "terms_accepted": True,
        "terms_version": "v1",
    }

    r_reg = client.post(url_reg, payload, format="json")
    assert r_reg.status_code == 201, r_reg.data

    # --- Mark email as verified (so login is allowed) ---
    u = User.objects.get(username="alice")
    UserProfile.objects.update_or_create(
        user=u,
        defaults={"email_verified": True},
    )

    # --- Login (good password) ---
    url_login = reverse("v1:auth-login")
    r_login = client.post(
        url_login,
        {"identifier": "alice", "password": "Pass12345!"},
        format="json",
    )
    assert r_login.status_code == 200, r_login.data
    assert "access" in r_login.data and "refresh" in r_login.data

    # --- Login (bad password) ---
    r_bad = client.post(
        url_login,
        {"identifier": "alice", "password": "WRONG"},
        format="json",
    )
    assert r_bad.status_code == 400, r_bad.data
