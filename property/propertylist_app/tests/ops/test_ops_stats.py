import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

@pytest.mark.django_db
def test_ops_stats_requires_admin_and_returns_keys():
    # Non-admin → 403
    u = User.objects.create_user(username="user", password="pass123", email="u@example.com")
    c = APIClient(); c.force_authenticate(user=u)
    url = reverse("v1:ops-stats")
    r_forbidden = c.get(url)
    assert r_forbidden.status_code == 403

    # Admin → 200 with expected keys
    admin = User.objects.create_user(username="admin", password="pass123", email="a@example.com", is_staff=True, is_superuser=True)
    c2 = APIClient(); c2.force_authenticate(user=admin)
    r_ok = c2.get(url)
    assert r_ok.status_code == 200, r_ok.data

    data = r_ok.json()
    for key in ["listings", "users", "bookings", "payments", "messages", "reports", "categories"]:
        assert key in data, f"missing '{key}' in payload"
