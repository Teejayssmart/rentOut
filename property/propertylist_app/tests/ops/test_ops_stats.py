import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


@pytest.mark.django_db
def test_ops_stats_requires_admin_and_returns_keys():
    # Non-admin → 403
    u = User.objects.create_user(username="user", password="pass123", email="u@example.com")
    c = APIClient()
    c.force_authenticate(user=u)
    url = "/api/v1/ops/stats/"
    r_forbidden = c.get(url)
    assert r_forbidden.status_code == 403

    # Admin → 200 with expected keys
    admin = User.objects.create_user(
        username="admin",
        password="pass123",
        email="a@example.com",
        is_staff=True,
        is_superuser=True,
    )
    c2 = APIClient()
    c2.force_authenticate(user=admin)
    r_ok = c2.get(url)
    assert r_ok.status_code == 200, r_ok.data

    body = r_ok.json()
    assert body.get("ok") is True
    assert "data" in body
    assert isinstance(body["data"], dict)

    data = body["data"]
    for key in ["listings", "users", "bookings", "payments", "messages", "reports", "categories"]:
        assert key in data, f"missing '{key}' in payload"