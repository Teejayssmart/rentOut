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

    login_url = reverse("v1:auth-login")
    resp = api_client.post(login_url, {"identifier": "bob", "password": "pass1234"}, format="json")
    assert resp.status_code == status.HTTP_200_OK, resp.data

    refresh = resp.data["refresh"]

    refresh_url = reverse("token_refresh")  # root urls, not namespaced
    r2 = api_client.post(refresh_url, {"refresh": refresh}, format="json")
    assert r2.status_code == status.HTTP_200_OK, r2.data
    assert "access" in r2.data
