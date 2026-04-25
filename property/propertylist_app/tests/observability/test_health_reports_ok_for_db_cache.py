import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_reports_ok_for_db_cache():
    """
    Verifies that the /health/ endpoint:
       responds with HTTP 200
       includes ok envelope with data.status == "ok"
       confirms database connectivity (db=True)
       confirms cache is reachable before the endpoint call
    """
    client = APIClient()
    url = reverse("v1:health")

    # Ensure cache works before calling endpoint
    cache.set("test_key", "test_value", 10)
    assert cache.get("test_key") == "test_value"

    # Capture DB query count (should at least ping once)
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)

    assert response.status_code == 200, response.content

    body = response.json()
    assert body.get("ok") is True
    assert "data" in body
    assert isinstance(body["data"], dict)

    data = body["data"]
    assert data.get("status") == "ok"
    assert data.get("db") is True

    # Endpoint should still touch DB at least once
    assert len(ctx) >= 1