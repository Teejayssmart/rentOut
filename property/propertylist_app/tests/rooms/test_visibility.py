import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from propertylist_app.models import Room, RoomCategorie
from propertylist_app.tasks import expire_paid_listings


@pytest.mark.django_db
def test_hidden_room_not_in_list_or_search():
    """
    Hidden or expired rooms must not appear in the public room list or search results.
    """
    cat = RoomCategorie.objects.create(name="Standard", active=True)

    visible = Room.objects.create(
        title="Public Room", category=cat, price_per_month=600, status="active"
    )
    hidden = Room.objects.create(
        title="Hidden Room", category=cat, price_per_month=700, status="hidden"
    )
    expired = Room.objects.create(
        title="Expired Room",
        category=cat,
        price_per_month=800,
        status="active",
        paid_until=timezone.now().date() - timedelta(days=1),
    )

    client = APIClient()

    # --- Room list ---
    r_list = client.get("/api/v1/rooms/")
    assert r_list.status_code == 200
    titles = [r["title"] for r in r_list.json()]
    assert "Public Room" in titles
    assert "Hidden Room" not in titles
    assert "Expired Room" not in titles

        # --- Search endpoint ---
    r_search = client.get("/api/v1/search/rooms/?q=Room")
    assert r_search.status_code == 200

    data = r_search.json()
    items = data if isinstance(data, list) else data.get("results", data)
    titles = [i["title"] for i in items]

    assert "Public Room" in titles
    assert "Hidden Room" not in titles
    assert "Expired Room" not in titles


@pytest.mark.django_db
def test_expired_room_hidden_after_scheduler():
    """
    When the scheduler runs, any room past its paid_until date should be auto-hidden.
    """
    cat = RoomCategorie.objects.create(name="Premium", active=True)
    room = Room.objects.create(
        title="Old Listing",
        category=cat,
        price_per_month=950,
        status="active",
        paid_until=timezone.now().date() - timedelta(days=1),
    )

    expire_paid_listings()  # run the scheduled job manually

    room.refresh_from_db()
    assert room.status == "hidden", "Scheduler did not hide expired room"
