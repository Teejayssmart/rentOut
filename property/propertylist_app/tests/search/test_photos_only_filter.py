import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth.models import User

from propertylist_app.models import RoomCategorie, Room, RoomImage


@pytest.mark.django_db
def test_search_photos_only_returns_rooms_with_legacy_or_approved_photos():
    owner = User.objects.create_user(username="o1", password="pass123", email="o1@example.com")
    cat = RoomCategorie.objects.create(name="Any", active=True)

    # Room A: no legacy image + no RoomImage => should NOT return
    r_no = Room.objects.create(title="NoPhotos", category=cat, price_per_month=800, property_owner=owner)

    # Room B: has legacy image => should return
    r_legacy = Room.objects.create(
        title="LegacyPhoto", category=cat, price_per_month=800, property_owner=owner, image="rooms/x.jpg"
    )

    # Room C: has RoomImage approved => should return
    r_img = Room.objects.create(title="ApprovedPhoto", category=cat, price_per_month=800, property_owner=owner)
    RoomImage.objects.create(room=r_img, image="rooms/y.jpg", status="approved")


    url = reverse("v1:search-rooms")
    res = APIClient().get(url, {"photos_only": "true"})
    assert res.status_code == 200
    results = res.data.get("results", res.data)
    titles = {x["title"] for x in results}

    assert "NoPhotos" not in titles
    assert "LegacyPhoto" in titles
    assert "ApprovedPhoto" in titles
