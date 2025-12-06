from django.contrib.auth.models import User
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase


class HomePageTests(APITestCase):
    """
    Basic tests for the public /api/home/ endpoint.

    We keep these tests deliberately simple so they don't depend on
    specific layout or Redis / Celery, just that the route exists and
    works for both anonymous and authenticated users.
    """

    def setUp(self):
        # Simple user we can use for authenticated checks
        self.user = User.objects.create_user(
            username="home_tester",
            email="home_tester@example.com",
            password="testpass123",
        )
        # URL for the homepage API.  Because app_name="api" and the
        # name in urls.py is "api-home", the full name is "api:api-home".
        self.url = reverse("api:api-home")

    def test_homepage_anon_can_access(self):
        """
        Anonymous visitors should be able to see the homepage data.
        This matches the public marketing homepage in the Figma flow.
        """
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # We only assert it's some JSON object/array; we don't lock the
        # test to any particular payload structure.
        self.assertIsNotNone(response.data)

    def test_homepage_authenticated_can_access(self):
        """
        Logged-in users should also get 200 from the homepage endpoint.
        (Dropdown profile menu, My listings, My bookings all start from here.)
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data)
