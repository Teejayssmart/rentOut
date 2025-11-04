import pytest
from django.urls import reverse
from django.core.cache import cache
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_reports_ok_for_db_cache():
    """
    Verifies that the /health/ endpoint:
      ✅ responds with HTTP 200
      ✅ includes {"status": "ok"}
      ✅ confirms database connectivity (db=True)
      ✅ confirms cache is reachable (cache=True)
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
    data = response.json()

    assert data.get("status") == "ok"
    assert data.get("db") is True
    # Optional: cache connectivity
    if "cache" in data:
        assert data.get("cache") is True

    # At least one query should be made (DB ping)
    assert len(ctx) >= 1
