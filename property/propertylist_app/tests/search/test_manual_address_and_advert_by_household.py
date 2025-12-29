import pytest
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, UserProfile


@pytest.mark.django_db
def test_search_manual_address_filters_by_street_and_city():
    """
    GET /api/search/rooms/?street=...&city=...
    Should filter against Room.location (icontains).
    """
    owner = User.objects.create_user(username="addr_owner", password="pass123", email="addr_owner@example.com")
    cat = RoomCategorie.objects.create(name="Any", active=True)

    # Matches street+city
    Room.objects.create(
        title="Match",
        category=cat,
        price_per_month=800,
        property_owner=owner,
        status="active",
        location="10 Downing Street, London",
    )

    # Does not match (different city)
    Room.objects.create(
        title="NoMatch",
        category=cat,
        price_per_month=800,
        property_owner=owner,
        status="active",
        location="1 High Street, Manchester",
    )

    url = reverse("v1:search-rooms")
    res = APIClient().get(url, {"street": "Downing", "city": "London"})
    assert res.status_code == 200, res.data

    results = res.data.get("results", res.data)
    titles = {x["title"] for x in results}

    assert "Match" in titles
    assert "NoMatch" not in titles


@pytest.mark.django_db
def test_search_advert_by_household_filters_by_userprofile_role_detail():
    """
    GET /api/search/rooms/?advert_by_household=live_in_landlord
    Should filter by property_owner__profile__role_detail.
    """
    cat = RoomCategorie.objects.create(name="Any", active=True)

    # Owner A: live_in_landlord
    owner_a = User.objects.create_user(username="owner_a", password="pass123", email="owner_a@example.com")
    UserProfile.objects.get_or_create(user=owner_a)
    owner_a.profile.role_detail = "live_in_landlord"
    owner_a.profile.save()

    Room.objects.create(
        title="LiveInRoom",
        category=cat,
        price_per_month=900,
        property_owner=owner_a,
        status="active",
        location="London",
    )

    # Owner B: current_flatmate
    owner_b = User.objects.create_user(username="owner_b", password="pass123", email="owner_b@example.com")
    UserProfile.objects.get_or_create(user=owner_b)
    owner_b.profile.role_detail = "current_flatmate"
    owner_b.profile.save()

    Room.objects.create(
        title="FlatmateRoom",
        category=cat,
        price_per_month=900,
        property_owner=owner_b,
        status="active",
        location="London",
    )

    url = reverse("v1:search-rooms")
    res = APIClient().get(url, {"advert_by_household": "live_in_landlord"})
    assert res.status_code == 200, res.data

    results = res.data.get("results", res.data)
    titles = {x["title"] for x in results}

    assert "LiveInRoom" in titles
    assert "FlatmateRoom" not in titles
