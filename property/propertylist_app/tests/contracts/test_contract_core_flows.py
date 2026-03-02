import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_contract_login_response_shape(user_factory):
    user_factory(username="u1", password="pass123", email="u1@example.com")
    client = APIClient()

    r = client.post(
        "/api/v1/auth/login/",
        {"identifier": "u1", "password": "pass123"},
        format="json",
    )
    assert r.status_code == 200, r.content
    payload = r.json()

    # Top-level envelope
    assert payload.get("ok") is True
    assert "data" in payload and isinstance(payload["data"], dict)

    data = payload["data"]

    # Tokens contract
    assert "tokens" in data and isinstance(data["tokens"], dict)
    tokens = data["tokens"]

    assert "access" in tokens and isinstance(tokens["access"], str) and tokens["access"]
    assert "refresh" in tokens and isinstance(tokens["refresh"], str) and tokens["refresh"]

    # Optional but useful: expiry timestamps are ISO-8601 date-time strings
    assert "access_expires_at" in tokens and isinstance(tokens["access_expires_at"], str)
    assert "refresh_expires_at" in tokens and isinstance(tokens["refresh_expires_at"], str)

    # User contract
    assert "user" in data and isinstance(data["user"], dict)
    assert "id" in data["user"]
    assert "email" in data["user"]

    # Profile contract (if you always include it)
    assert "profile" in data and isinstance(data["profile"], dict)