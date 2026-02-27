import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_contract_login_response_shape(user_factory):
    user_factory(username="u1", password="pass123", email="u1@example.com")
    client = APIClient()

    r = client.post("/api/v1/auth/login/", {"identifier": "u1", "password": "pass123"}, format="json")
    assert r.status_code == 200
    data = r.json()

    # contract (keep stable)
    assert "access" in data and isinstance(data["access"], str)
    assert "refresh" in data and isinstance(data["refresh"], str)
    assert "user" in data and isinstance(data["user"], dict)


@pytest.mark.django_db
def test_contract_search_rooms_shape():
    client = APIClient()
    r = client.get("/api/v1/search/rooms/?q=test")
    assert r.status_code == 200
    data = r.json()

    # typical DRF pagination
    assert "results" in data and isinstance(data["results"], list)
    assert "count" in data