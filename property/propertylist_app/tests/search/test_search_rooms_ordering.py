from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from rest_framework.test import APITestCase

from propertylist_app.models import Room, RoomCategorie


User = get_user_model()


def make_user(i=1):
    """Small helper to create a user."""
    return User.objects.create_user(
        username=f"user{i}",
        email=f"u{i}@ex.com",
        password="pass12345",
    )


def make_category(name="Central", active=True):
    return RoomCategorie.objects.create(name=name, active=active)


def make_room(
    *,
    owner=None,
    cat=None,
    title="Room A",
    price=750,
    avg_rating=0.0,
):
    """
    Create a minimal valid Room that satisfies NOT NULL fields.
    Mirrors the helper used in other tests.
    """
    owner = owner or make_user()
    cat = cat or make_category()
    return Room.objects.create(
        title=title,
        description="",
        price_per_month=Decimal(price),
        location="",
        category=cat,
        available_from=date.today(),
        is_available=True,
        furnished=False,
        bills_included=False,
        property_owner=owner,
        image=None,
        number_of_bedrooms=1,
        number_of_bathrooms=1,
        property_type="flat",
        parking_available=False,
        avg_rating=avg_rating,
        number_rating=0,
        status="active",
    )


class RoomsAltOrderingTests(APITestCase):
    """
    Tests for /api/rooms-alt/ (RoomListGV)
    - ordering by average rating
    - limit/offset pagination
    """

    def test_rooms_alt_order_by_avg_rating_desc(self):
        """
        When we call ?ordering=-avg_rating, results should be
        ordered by avg_rating descending.
        """
        owner = make_user()
        cat_central = make_category("Central")
        cat_suburbs = make_category("Suburbs")

        r1 = make_room(
            owner=owner,
            cat=cat_suburbs,
            title="Room 1",
            price=900,
            avg_rating=4.2,
        )
        r2 = make_room(
            owner=owner,
            cat=cat_central,
            title="Room 2",
            price=1200,
            avg_rating=4.9,
        )
        r3 = make_room(
            owner=owner,
            cat=cat_central,
            title="Room 3",
            price=800,
            avg_rating=3.5,
        )

        url = reverse("v1:room-list-alt") + "?ordering=-avg_rating"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("results", resp.data)

        titles = [item["title"] for item in resp.data["results"]]
        # First three should be ordered by rating desc: 4.9, 4.2, 3.5
        self.assertGreaterEqual(len(titles), 3)
        self.assertEqual(titles[:3], ["Room 2", "Room 1", "Room 3"])

    def test_rooms_alt_pagination_limit_offset(self):
        """
        Limit/offset pagination should respect ?limit=3&offset=3.
        """
        owner = make_user()
        cat = make_category("Central")

        # Create 7 rooms so we have enough to page through
        for i in range(7):
            make_room(
                owner=owner,
                cat=cat,
                title=f"R{i}",
                price=500 + i,
                avg_rating=4.0,
            )

        url = reverse("v1:room-list-alt") + "?limit=3&offset=3"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        # DRF LimitOffsetPagination returns: {count, next, previous, results}
        self.assertIn("count", resp.data)
        self.assertIn("results", resp.data)

        self.assertGreaterEqual(resp.data["count"], 7)
        self.assertEqual(len(resp.data["results"]), 3)
