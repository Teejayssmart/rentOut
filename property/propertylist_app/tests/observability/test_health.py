import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.test.utils import CaptureQueriesContext
from django.db import connection

@pytest.mark.django_db
def test_health_endpoint_returns_ok_and_pings_db():
    client = APIClient()
    url = reverse("v1:health")

    with CaptureQueriesContext(connection) as q:
        r = client.get(url)

    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    # Should touch the DB once for the SELECT 1 (allow small variance)
    assert data.get("db") is True
    assert len(q) >= 1
