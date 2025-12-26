import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_create_password_success_for_social_user():
    u = User.objects.create_user(username="socialuser", email="social@example.com")
    u.set_unusable_password()
    u.save(update_fields=["password"])

    c = APIClient()
    c.force_authenticate(user=u)

    url = reverse("api:user-create-password")
    r = c.post(url, {"new_password": "StrongPass123!@", "confirm_password": "StrongPass123!@"}, format="json")
    assert r.status_code == 200

    u.refresh_from_db()
    assert u.has_usable_password() is True
    assert u.check_password("StrongPass123!@") is True


def test_create_password_rejects_if_password_already_exists():
    u = User.objects.create_user(username="normaluser", password="ExistingPass123!@")

    c = APIClient()
    c.force_authenticate(user=u)

    url = reverse("api:user-create-password")
    r = c.post(url, {"new_password": "NewPass123!@", "confirm_password": "NewPass123!@"}, format="json")
    assert r.status_code == 400


def test_create_password_rejects_mismatch():
    u = User.objects.create_user(username="socialuser2", email="social2@example.com")
    u.set_unusable_password()
    u.save(update_fields=["password"])

    c = APIClient()
    c.force_authenticate(user=u)

    url = reverse("api:user-create-password")
    r = c.post(url, {"new_password": "StrongPass123!@", "confirm_password": "Different123!@"}, format="json")
    assert r.status_code == 400
    assert "confirm_password" in r.data
