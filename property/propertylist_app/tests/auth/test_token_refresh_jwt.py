import pytest
from django.urls import reverse
from rest_framework import status

from propertylist_app.models import UserProfile


@pytest.mark.django_db
def test_refresh_token_returns_new_access(api_client, django_user_model):
    user = django_user_model.objects.create_user(
        username="bob",
        email="bob@example.com",
        password="pass1234",
    )
    UserProfile.objects.update_or_create(user=user, defaults={"email_verified": True})

    # Login (your login response uses the unified envelope)
    login_url = reverse("v1:auth-login")
    resp = api_client.post(
        login_url,
        {"identifier": "bob", "password": "pass1234"},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.data

    refresh = resp.data["data"]["tokens"]["refresh"]

    # Refresh token endpoint (your urls.py names this v1:auth-token-refresh)
    refresh_url = reverse("v1:auth-token-refresh")
    r2 = api_client.post(refresh_url, {"refresh": refresh}, format="json")

    assert r2.status_code == status.HTTP_200_OK, r2.data
    assert r2.data.get("ok") is True
    assert "data" in r2.data
    assert "access" in r2.data["data"]
    assert r2.data["data"]["access"]

   
