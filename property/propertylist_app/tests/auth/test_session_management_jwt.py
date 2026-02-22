import pytest
from django.urls import reverse
from rest_framework import status
from propertylist_app.models import UserProfile


@pytest.mark.django_db
def test_logout_blacklists_refresh_token_cannot_refresh_anymore(api_client, django_user_model):
    # create user
    user = django_user_model.objects.create_user(
        username="bob",
        email="bob@example.com",
        password="pass1234",
    )
    # your login blocks unverified emails
    UserProfile.objects.update_or_create(user=user, defaults={"email_verified": True})

    login_url = reverse("v1:auth-login")
    logout_url = reverse("v1:auth-logout")
    refresh_url = reverse("v1:auth-token-refresh")


    # login → get tokens (your login expects "identifier", not "username")
    resp = api_client.post(login_url, {"identifier": "bob", "password": "pass1234"}, format="json")
    assert resp.status_code == status.HTTP_200_OK, resp.data

    access = resp.data["data"]["tokens"]["access"]
    refresh = resp.data["data"]["tokens"]["refresh"]


    # logout → blacklist refresh
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    out = api_client.post(logout_url, {"refresh": refresh}, format="json")
    assert out.status_code in (200, 204), out.data

    # refresh should now fail
    r2 = api_client.post(refresh_url, {"refresh": refresh}, format="json")
    assert r2.status_code in (400, 401), r2.data


@pytest.mark.django_db
def test_blacklisted_refresh_token_stays_blacklisted_on_reuse(api_client, django_user_model):
    user = django_user_model.objects.create_user(
        username="kate",
        email="kate@example.com",
        password="pass1234",
    )
    UserProfile.objects.update_or_create(user=user, defaults={"email_verified": True})

    login_url = reverse("v1:auth-login")
    logout_url = reverse("v1:auth-logout")
    refresh_url = "/api/v1/auth/token/refresh/"

    resp = api_client.post(login_url, {"identifier": "kate", "password": "pass1234"}, format="json")
    assert resp.status_code == status.HTTP_200_OK, resp.data

    access = resp.data["data"]["tokens"]["access"]
    refresh = resp.data["data"]["tokens"]["refresh"]


    # logout once
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    out = api_client.post(logout_url, {"refresh": refresh}, format="json")
    assert out.status_code in (200, 204), out.data

    # refresh fails
    r1 = api_client.post(refresh_url, {"refresh": refresh}, format="json")
    assert r1.status_code in (400, 401), r1.data

    # refresh fails again (still blacklisted)
    r2 = api_client.post(refresh_url, {"refresh": refresh}, format="json")
    assert r2.status_code in (400, 401), r2.data
