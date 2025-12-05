from datetime import date

from django.contrib.auth.models import User
from django.urls import reverse

from rest_framework.test import APITestCase
from rest_framework import status


class ProfileOnboardingTests(APITestCase):
    def setUp(self):
        # Simple logged-in user for all tests
        self.user = User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="Testpass123!",
        )
        self.client.force_authenticate(user=self.user)
        self.url = reverse("api:user-profile")  # /api/users/me/profile/

    def test_update_profile_valid_payload_succeeds(self):
        payload = {
            "phone": "07123456789",
            "occupation": "Software Engineer",
            "postcode": "so14 3fh",
            "date_of_birth": "1990-01-01",
            "gender": "male",
            "about_you": "I like quiet, tidy homes.",
            "role": "landlord",
            "role_detail": "live_in_landlord",
            "address_manual": "10 High Street, Southampton",
        }

        resp = self.client.patch(self.url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        profile = self.user.profile

        self.assertEqual(profile.phone, "07123456789")
        self.assertEqual(profile.occupation, "Software Engineer")
        # postcode should be normalised by validate_postcode / normalize_uk_postcode
        self.assertEqual(profile.postcode, "SO14 3FH")
        self.assertEqual(str(profile.date_of_birth), "1990-01-01")
        self.assertEqual(profile.gender, "male")
        self.assertEqual(profile.about_you, "I like quiet, tidy homes.")
        self.assertEqual(profile.role, "landlord")
        self.assertEqual(profile.role_detail, "live_in_landlord")
        self.assertEqual(profile.address_manual, "10 High Street, Southampton")

    def test_update_profile_underage_rejected(self):
        # Clearly under 18 for many years
        payload = {
            "date_of_birth": "2015-01-01",
        }

        resp = self.client.patch(self.url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date_of_birth", resp.data)

    def test_update_profile_invalid_gender_rejected(self):
        payload = {
            "gender": "alien",
        }

        resp = self.client.patch(self.url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("gender", resp.data)

    def test_update_profile_all_fields_optional_when_empty(self):
        """
        Frontend can send an empty payload or clear optional fields
        without causing errors.
        """
        payload = {
            "occupation": "",
            "postcode": "",
            "date_of_birth": None,
            "gender": "",
            "about_you": "",
            "role_detail": "",
            "address_manual": "",
        }

        resp = self.client.patch(self.url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
