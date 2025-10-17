import pytest
from django.core.cache import cache
from django.urls import reverse
from django.test.utils import CaptureQueriesContext, override_settings
from django.db import connection
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from propertylist_app.models import Room, RoomCategorie

User = get_user_model()

TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "tests-locmem-cache",  # stable location so hits persist in-process
    }
}

# Disable DRF auth classes for these tests to avoid "Vary: Cookie" etc.
REST_FRAMEWORK_MINIMAL = {"DEFAULT_AUTHENTICATION_CLASSES": []}


@override_settings(CACHES=TEST_CACHES, REST_FRAMEWORK=REST_FRAMEWORK_MINIMAL)
@pytest.mark.django_db
def test_search_rooms_response_is_cached():
    cache.clear()

    owner = User.objects.create_user(username="o", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Any", active=True)
    Room.objects.create(
        title="Cozy flat in London",
        description="Nice place",
        price_per_month=1000,
        location="London SW1A 1AA",
        category=cat,
        property_owner=owner,
        avg_rating=4.5,
    )

    client = APIClient()
    url = reverse("v1:search-rooms")

    # First call: should hit DB
    with CaptureQueriesContext(connection) as q1:
        r1 = client.get(url, {"q": "cozy"})
    assert r1.status_code == 200
    first_queries = len(q1)

    # Second identical call: should come from cache
    with CaptureQueriesContext(connection) as q2:
        r2 = client.get(url, {"q": "cozy"})
    assert r2.status_code == 200
    second_queries = len(q2)

    assert second_queries < first_queries, f"Expected cached response. first={first_queries}, second={second_queries}"


@override_settings(CACHES=TEST_CACHES, REST_FRAMEWORK=REST_FRAMEWORK_MINIMAL)
@pytest.mark.django_db
def test_rooms_alt_list_response_is_cached():
    cache.clear()

    owner = User.objects.create_user(username="owner2", password="pass123", email="o2@example.com")
    cat = RoomCategorie.objects.create(name="Any2", active=True)
    for i in range(3):
        Room.objects.create(
            title=f"Room {i}",
            description="...",
            price_per_month=900 + i * 10,
            location="Manchester M1 1AA",
            category=cat,
            property_owner=owner,
            avg_rating=4.0 + (i * 0.1),
        )

    client = APIClient()
    url = reverse("v1:room-list-alt")

    with CaptureQueriesContext(connection) as q1:
        r1 = client.get(url)
    assert r1.status_code == 200
    first_queries = len(q1)

    with CaptureQueriesContext(connection) as q2:
        r2 = client.get(url)
    assert r2.status_code == 200
    second_queries = len(q2)

    assert second_queries < first_queries, f"Expected cached response. first={first_queries}, second={second_queries}"
