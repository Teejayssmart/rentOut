import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile

API = "/api"

@pytest.fixture
def api():
    return APIClient()

@pytest.mark.django_db
def test_login_with_email_different_case_ok(api):
    User = get_user_model()
    u = User.objects.create_user(username="caseuser", email="case@example.com", password="Str0ng!Pass")
    p, _ = UserProfile.objects.get_or_create(user=u, defaults={"role": "seeker"})
    p.email_verified = True
    p.email_verified_at = timezone.now()
    p.save()

    res = api.post(f"{API}/auth/login/", {"identifier": "CASE@EXAMPLE.COM", "password": "Str0ng!Pass"}, format="json")
    assert res.status_code == 200, res.data
    assert "data" in res.data and res.data["ok"] is True
    assert "tokens" in res.data["data"]
    assert "access" in res.data["data"]["tokens"]
    assert "refresh" in res.data["data"]["tokens"]


@pytest.mark.django_db
def test_login_with_username_ok(api):
    User = get_user_model()
    u = User.objects.create_user(username="nameuser", email="name@example.com", password="Str0ng!Pass")
    p, _ = UserProfile.objects.get_or_create(user=u, defaults={"role": "landlord"})
    p.email_verified = True
    p.email_verified_at = timezone.now()
    p.save()

    res = api.post(f"{API}/auth/login/", {"identifier": "nameuser", "password": "Str0ng!Pass"}, format="json")
    assert res.status_code == 200, res.data
