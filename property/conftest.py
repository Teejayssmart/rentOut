# property/conftest.py
import os
import uuid
import pytest
from django.core.cache import cache

@pytest.fixture(autouse=True)
def clear_cache_between_tests(settings):
    # Make sure throttle counters and any cached responses don’t leak across tests
    cache.clear()
    yield
    cache.clear()

@pytest.fixture(autouse=True)
def unique_cache_location_for_session(settings):
    """
    Ensure this test session uses a unique LocMem cache 'LOCATION'
    so it doesn't reuse a stale cache namespace from any prior run.
    """
    caches = settings.CACHES.copy()
    default = caches.get("default", {}).copy()
    default["LOCATION"] = f"pytest-cache-{os.getpid()}-{uuid.uuid4()}"
    caches["default"] = default
    settings.CACHES = caches

