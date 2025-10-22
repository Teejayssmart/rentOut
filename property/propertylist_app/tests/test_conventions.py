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


class TestMessagesCursorPagination(BaseAPITest):
    def setUp(self):
        super().setUp()
        # Create a thread with self.user and other participant
        self.thread = MessageThread.objects.create()
        self.thread.participants.set([self.user, self.other])

        # Create 6 messages so we exceed default page_size=5 in RoomCPagination
        base = timezone.now() - timedelta(minutes=6)
        self.msgs = []
        for i in range(6):
            m = Message.objects.create(
                thread=self.thread,
                sender=self.user if i % 2 == 0 else self.other,
                body=f"Message {i+1}",
                created=base + timedelta(minutes=i),
            )
            self.msgs.append(m)

    def test_messages_default_ordering_desc_and_cursor_next(self):
        """
        /messages/threads/<id>/messages/ uses cursor pagination with default ordering -created.
        Should return newest first and include 'next' cursor when more than page_size.
        """
        url = reverse("v1:thread-messages", kwargs={"thread_id": self.thread.id})  # ← FIXED: Added v1: namespace
        resp = self.client.get(url)  # first page
        self.assertEqual(resp.status_code, 200)

        # Cursor pagination returns keys: next, previous, results
        self.assertIn("results", resp.data)
        self.assertIn("next", resp.data)

        results = resp.data["results"]
        self.assertTrue(len(results) <= 5)  # page_size=5 in RoomCPagination

        # Newest first: Message 6 should appear before 5, etc.
        bodies = [r["body"] for r in results]
        self.assertIn("Message 6", bodies[0])

        # If 'next' is present, following the cursor should give the remaining item(s)
        if resp.data["next"]:
            # DRF test client won't follow external URLs; call with cursor param instead
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(resp.data["next"]).query)
            cursor = q.get("record", [None])[0]
            resp2 = self.client.get(url, {"record": cursor})
            self.assertEqual(resp2.status_code, 200)
            self.assertGreaterEqual(len(resp2.data["results"]), 1)