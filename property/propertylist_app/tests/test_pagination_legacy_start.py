# propertylist_app/tests/test_pagination_legacy_start.py

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import RoomCategorie, Room


@pytest.mark.django_db
def test_rooms_list_supports_legacy_start_param():
    """
    Legacy support: ?start=N behaves like ?offset=N.
    Canonical should remain ?offset=N.
    """
    # Arrange: create enough rooms to paginate
    cat = RoomCategorie.objects.create(name="Standard", active=True)
    for i in range(5):
        Room.objects.create(
            title=f"Room {i}",
            category=cat,
            price_per_month=500 + i,
            status="active",
        )

    client = APIClient()
    url = reverse("v1:room-list")

    # Act
    r_offset = client.get(url, {"limit": 2, "offset": 0})
    r_start = client.get(url, {"limit": 2, "start": 0})

    # Assert
    assert r_offset.status_code == 200
    assert r_start.status_code == 200
    assert r_offset.data["results"] == r_start.data["results"]


@pytest.mark.django_db
def test_rooms_list_legacy_start_affects_pagination_links_like_offset():
    """
    This verifies legacy ?start=N is interpreted as the offset value, without
    relying on queryset ordering (which may be unstable if the view doesn't order_by()).
    """
    cat = RoomCategorie.objects.create(name="Standard", active=True)
    for i in range(5):
        Room.objects.create(
            title=f"Room {i}",
            category=cat,
            price_per_month=500 + i,
            status="active",
        )

    client = APIClient()
    url = reverse("v1:room-list")

    # Using legacy start=2 with limit=2 should yield:
    # previous offset = max(2-2, 0) = 0
    # next offset = 2+2 = 4
    r = client.get(url, {"limit": 2, "start": 2})

    assert r.status_code == 200
    assert "count" in r.data
    assert "next" in r.data
    assert "previous" in r.data
    assert "results" in r.data

    # next/previous links should be generated using canonical param name "offset"
    # (not "start"), and should reflect the offset math above.
    if r.data["previous"]:
        assert "offset=0" in r.data["previous"]
        assert "limit=2" in r.data["previous"]
        assert "start=" not in r.data["previous"]

    if r.data["next"]:
        assert "offset=4" in r.data["next"]
        assert "limit=2" in r.data["next"]
        assert "start=" not in r.data["next"]