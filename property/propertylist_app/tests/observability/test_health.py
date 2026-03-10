import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_endpoint_returns_ok_and_pings_db():
    client = APIClient()
    url = reverse("v1:health")

    with CaptureQueriesContext(connection) as q:
        r = client.get(url)

    assert r.status_code == 200

    body = r.json()
    assert body.get("ok") is True
    assert "data" in body
    assert isinstance(body["data"], dict)

    data = body["data"]
    assert data.get("status") == "ok"
    assert data.get("db") is True

    # should hit the DB at least once for the health ping
    assert len(q) >= 1