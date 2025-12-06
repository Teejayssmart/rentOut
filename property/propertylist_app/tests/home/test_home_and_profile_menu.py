from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from propertylist_app.models import Room, Booking

User = get_user_model()


class HomePageTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="homeuser",
            email="home@example.com",
            password="testpass123",
        )
        self.url = reverse("api:api-home")

    def test_homepage_anon_can_access(self):
        """Anonymous visitors should see the homepage (public)."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsInstance(resp.data, dict)

    def test_homepage_authenticated_can_access(self):
        """Logged-in users should also see the homepage."""
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsInstance(resp.data, dict)


class MyListingsTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner1",
            email="owner1@example.com",
            password="testpass123",
        )
        self.other = User.objects.create_user(
            username="owner2",
            email="owner2@example.com",
            password="testpass123",
        )

        # Rooms for self.owner
        self.room1 = Room.objects.create(
            title="Owner1 Room 1",
            description="Nice room 1",
            price_per_month=500,
            location="SW1A 1AA",
            property_owner=self.owner,
            property_type="flat",
        )
        self.room2 = Room.objects.create(
            title="Owner1 Room 2",
            description="Nice room 2",
            price_per_month=600,
            location="SW1A 2AA",
            property_owner=self.owner,
            property_type="house",
        )

        # Room for other user
        self.other_room = Room.objects.create(
            title="Other User Room",
            description="Not mine",
            price_per_month=700,
            location="SW1A 3AA",
            property_owner=self.other,
            property_type="studio",
        )

        self.url = reverse("api:rooms-mine")

    def test_my_rooms_requires_authentication(self):
        """My Listings should not be visible to anonymous users."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_my_rooms_returns_only_current_user_rooms(self):
        """My Listings should only return rooms owned by the logged-in user."""
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        payload = resp.data
        items = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertIsInstance(items, list)

        returned_ids = {item["id"] for item in items}
        self.assertIn(self.room1.id, returned_ids)
        self.assertIn(self.room2.id, returned_ids)
        self.assertNotIn(self.other_room.id, returned_ids)



class MyBookingsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="booker",
            email="booker@example.com",
            password="testpass123",
        )
        self.other = User.objects.create_user(
            username="otherbooker",
            email="other@example.com",
            password="testpass123",
        )

        # Create a room for bookings
        self.room = Room.objects.create(
            title="Room for bookings",
            description="Booking test room",
            price_per_month=550,
            location="SW1A 4AA",
            property_owner=self.other,
            property_type="flat",
        )

        now = timezone.now()
        # Booking for self.user
        self.booking_user = Booking.objects.create(
            user=self.user,
            room=self.room,
            start=now + timedelta(days=1),
            end=now + timedelta(days=1, hours=1),
        )
        # Booking for other user
        self.booking_other = Booking.objects.create(
            user=self.other,
            room=self.room,
            start=now + timedelta(days=2),
            end=now + timedelta(days=2, hours=1),
        )

        self.url = reverse("api:bookings-list-create")

    def test_my_bookings_requires_authentication(self):
        """My Bookings list should require authentication."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_my_bookings_only_returns_current_user_bookings(self):
        """My Bookings should only include bookings belonging to the logged-in user."""
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        payload = resp.data
        items = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertIsInstance(items, list)

        returned_ids = {item["id"] for item in items}
        self.assertIn(self.booking_user.id, returned_ids)
        self.assertNotIn(self.booking_other.id, returned_ids)



class ProfileMenuEndpointsTests(APITestCase):
    """
    These tests treat the profile dropdown as a group of backend endpoints:

    - /api/users/me/
    - /api/users/me/profile/
    - /api/rooms/mine/
    - /api/bookings/

    They should:
    - be protected for anonymous users (401 where appropriate)
    - work (200) for authenticated users.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="menuuser",
            email="menu@example.com",
            password="testpass123",
        )

        self.urls = {
            "me": reverse("api:user-me"),
            "profile": reverse("api:user-profile"),
            "my_rooms": reverse("api:rooms-mine"),
            "my_bookings": reverse("api:bookings-list-create"),
        }

    def test_profile_menu_links_require_auth_for_protected_endpoints(self):
        """Anonymous user should be blocked from 'me', 'profile', 'my rooms', 'my bookings'."""
        for name, url in self.urls.items():
            resp = self.client.get(url)
            self.assertEqual(
                resp.status_code,
                status.HTTP_401_UNAUTHORIZED,
                msg=f"{name} should require auth but got {resp.status_code}",
            )

    def test_profile_menu_links_work_for_authenticated_user(self):
        """Logged-in user should get 200 OK from all profile dropdown endpoints."""
        self.client.force_authenticate(user=self.user)

        for name, url in self.urls.items():
            resp = self.client.get(url)
            self.assertEqual(
                resp.status_code,
                status.HTTP_200_OK,
                msg=f"{name} returned {resp.status_code}: {resp.content}",
            )
