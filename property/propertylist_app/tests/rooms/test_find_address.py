import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_find_address_requires_postcode():
    client = APIClient()
    resp = client.get("/api/v1/search/find-address/")

    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["message"] == "Query param 'postcode' is required."


@pytest.mark.django_db
def test_find_address_returns_addresses(monkeypatch):
    client = APIClient()

    def fake_fetch(postcode):
        assert postcode == "SW1A 1AA"
        return [
            {"id": "addr_1", "label": "10 Downing Street, Westminster, London, SW1A 2AA"},
            {"id": "addr_2", "label": "11 Downing Street, Westminster, London, SW1A 2AB"},
        ]

    monkeypatch.setattr(
        "propertylist_app.api.views.public._fetch_ideal_postcodes_suggestions",
        fake_fetch,
    )

    resp = client.get("/api/v1/search/find-address/?postcode=SW1A 1AA")
    assert resp.status_code == 200

    data = resp.json()
    assert data["ok"] is True
    assert "data" in data
    assert "addresses" in data["data"]
    assert len(data["data"]["addresses"]) == 2
    assert data["data"]["addresses"][0]["id"] == "addr_1"
    assert "Downing Street" in data["data"]["addresses"][0]["label"]


@pytest.mark.django_db
def test_find_address_returns_empty_list(monkeypatch):
    client = APIClient()

    def fake_fetch(postcode):
        return []

    monkeypatch.setattr(
       "propertylist_app.api.views.public._fetch_ideal_postcodes_suggestions",
        fake_fetch,
    )

    resp = client.get("/api/v1/search/find-address/?postcode=ZZ1 1ZZ")
    assert resp.status_code == 200

    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["addresses"] == []