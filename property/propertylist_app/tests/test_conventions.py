from datetime import timedelta
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from propertylist_app.models import (
    Room,
    RoomCategorie,
    Booking,
    MessageThread,
    Message,
)

User = get_user_model()


class BaseAPITest(APITestCase):
    """
    Base test with authenticated user and clean test database.
    """
    def setUp(self):
        cache.clear()  # ← ADDED: Clear cache between tests
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="alice",
            password="pass1234",
            email="alice@example.com"
        )
        self.other = User.objects.create_user(
            username="bob",
            password="pass1234",
            email="bob@example.com"
        )
        self.client.force_authenticate(user=self.user)


class TestRoomsOrderingAndPagination(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.cat_a = RoomCategorie.objects.create(name="Central", active=True)
        self.cat_b = RoomCategorie.objects.create(name="Suburbs", active=True)

        # Create 3 rooms with different ratings/prices/categories
        self.r1 = Room.objects.create(
            title="Room 1", category=self.cat_b, price_per_month=900, avg_rating=4.2, property_owner=self.user
        )
        self.r2 = Room.objects.create(
            title="Room 2", category=self.cat_a, price_per_month=700, avg_rating=4.9, property_owner=self.user
        )
        self.r3 = Room.objects.create(
            title="Room 3", category=self.cat_a, price_per_month=800, avg_rating=3.8, property_owner=self.user
        )

    def test_rooms_alt_order_by_avg_rating_desc(self):
        """
        /rooms-alt/?ordering=-avg_rating should return highest rating first.
        """
        url = reverse("v1:room-list-alt")  # ← FIXED: Added v1: namespace
        resp = self.client.get(url, {"ordering": "-avg_rating"})
        self.assertEqual(resp.status_code, 200)
        titles = [r["title"] for r in resp.data["results"]]
        self.assertEqual(titles, ["Room 2", "Room 1", "Room 3"])

    def test_rooms_alt_pagination_limit_offset(self):
        """
        /rooms-alt/ uses RoomLOPagination (limit/offset). Ask for limit=2 → 2 items and a next page.
        """
        url = reverse("v1:room-list-alt")  # ← FIXED: Added v1: namespace
        resp = self.client.get(url, {"limit": 2, "offset": 0, "ordering": "category__name"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results", resp.data)
        self.assertEqual(len(resp.data["results"]), 2)
        # next should exist because we created 3 rooms
        self.assertTrue(resp.data["next"])


class TestBookingsOrdering(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.cat = RoomCategorie.objects.create(name="Central", active=True)
        self.room = Room.objects.create(
            title="Room A", category=self.cat, price_per_month=750, avg_rating=4.0, property_owner=self.other
        )

        now = timezone.now()
        # Two bookings with different created_at and start times
        self.b1 = Booking.objects.create(
            user=self.user,
            room=self.room,
            start=now + timedelta(days=1),
            end=now + timedelta(days=1, hours=1),
        )
        # manually adjust created_at to be older/newer if auto_now_add is used
        Booking.objects.filter(pk=self.b1.pk).update(created_at=now - timedelta(days=2))

        self.b2 = Booking.objects.create(
            user=self.user,
            room=self.room,
            start=now + timedelta(days=3),
            end=now + timedelta(days=3, hours=1),
        )
        Booking.objects.filter(pk=self.b2.pk).update(created_at=now - timedelta(days=1))

    def test_bookings_default_ordering_newest_first(self):
        """
        /bookings/ default ordering is -created_at (newest first).
        """
        url = reverse("v1:bookings-list-create")  # ← FIXED: Added v1: namespace
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        ids = [b["id"] for b in resp.data["results"]]
        # b2 is newer than b1
        self.assertEqual(ids, [self.b2.id, self.b1.id])

    def test_bookings_order_by_start_asc(self):
        """
        /bookings/?ordering=start should return the earliest start first.
        """
        url = reverse("v1:bookings-list-create")  # ← FIXED: Added v1: namespace
        resp = self.client.get(url, {"ordering": "start"})
        self.assertEqual(resp.status_code, 200)
        starts = [b["start"] for b in resp.data["results"]]
        # ensure chronological order (ISO strings compare in order)
        self.assertLess(starts[0], starts[1])


class TestMessagesLimitOffsetPagination(BaseAPITest):
    def setUp(self):
        super().setUp()

        # Create a thread with self.user and other participant
        self.thread = MessageThread.objects.create()
        self.thread.participants.set([self.user, self.other])

        # Create 6 messages
        base = timezone.now() - timedelta(minutes=6)

        for i in range(6):
            Message.objects.create(
                thread=self.thread,
                sender=self.user,
                body=f"Message {i+1}",
                created=base + timedelta(minutes=i),
            )

    def test_messages_default_ordering_desc_and_limit_offset(self):
        """
        Messages endpoint uses limit/offset pagination.
        Should return newest first.
        """

        url = reverse("v1:thread-messages", kwargs={"thread_id": self.thread.id})
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)

        # limit/offset structure
        self.assertIn("results", resp.data)

        results = resp.data["results"]

        # All 6 may appear since default PAGE_SIZE is larger
        self.assertGreaterEqual(len(results), 1)

        # Newest first
        bodies = [r["body"] for r in results]
        self.assertIn("Message 6", bodies[0])

        # If next exists, verify next page works
        if resp.data.get("next"):
            from urllib.parse import urlparse, parse_qs

            q = parse_qs(urlparse(resp.data["next"]).query)

            params = {}
            if "limit" in q:
                params["limit"] = q["limit"][0]
            if "offset" in q:
                params["offset"] = q["offset"][0]

            resp2 = self.client.get(url, params)

            self.assertEqual(resp2.status_code, 200)
            self.assertIn("results", resp2.data)