import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from propertylist_app.models import EmailOTP, UserProfile

User = get_user_model()


class OnboardingFlowTests(APITestCase):
    def _register_user(self):
        """
        Helper: register a new user through the API and return (user, response).
        """
        url = reverse("api:auth-register")
        payload = {
            "username": "onboarding_user",
            "email": "onboarding@example.com",
            "password": "Aa123456!",
            "password2": "Aa123456!",
            "first_name": "Onboard",
            "last_name": "User",
            "role": "seeker",
            "terms_accepted": True,
            "terms_version": "v1",
            "marketing_consent": False,
        }
        resp = self.client.post(url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

        user_id = resp.data["data"]["id"]
        user = User.objects.get(pk=user_id)
        return user, resp

    def _get_latest_otp(self, user):
        return EmailOTP.objects.filter(user=user).order_by("-created_at").first()

    def _get_latest_email_otp_code(self):
        self.assertTrue(mail.outbox, "Expected at least one email in outbox.")
        body = mail.outbox[-1].body
        match = re.search(r"(\d{6})", body)
        self.assertIsNotNone(match, f"Could not find 6-digit OTP in email body: {body}")
        return match.group(1)

    def test_full_onboarding_flow_success(self):
        """
        End-to-end happy path:
        - Register
        - Verify OTP
        - Update profile with onboarding fields
        """
        user, reg_resp = self._register_user()

        # OTP was created
        otp = self._get_latest_otp(user)
        self.assertIsNotNone(otp)

        # Use the plain 6-digit code from the sent email, not otp.code (hashed in DB)
        plain_code = self._get_latest_email_otp_code()

        verify_url = reverse("api:auth-verify-otp")
        verify_payload = {
            "user_id": user.id,
            "code": plain_code,
        }
        resp = self.client.post(verify_url, verify_payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        # Profile should be marked email_verified in DB
        profile = UserProfile.objects.get(user=user)
        self.assertTrue(profile.email_verified)

        # Now authenticate as this user and update profile fields
        self.client.force_authenticate(user=user)

        profile_url = reverse("api:user-profile")
        update_payload = {
            "occupation": "Software engineer",
            "postcode": "SW1A 1AA",
            "date_of_birth": "1990-01-01",
            "gender": "male",
            "about_you": "Friendly and tidy.",
            "role": "seeker",
            "role_detail": "current_flatmate",
            "address_manual": "10 Downing Street, London",
        }
        resp = self.client.patch(profile_url, update_payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        # Check values persisted correctly
        profile.refresh_from_db()
        self.assertEqual(profile.occupation, "Software engineer")
        self.assertEqual(profile.postcode, "SW1A 1AA")
        self.assertEqual(str(profile.date_of_birth), "1990-01-01")
        self.assertEqual(profile.gender, "male")
        self.assertEqual(profile.role, "seeker")
        self.assertEqual(profile.role_detail, "current_flatmate")
        self.assertEqual(profile.address_manual, "10 Downing Street, London")

    def test_otp_invalid_code_fails(self):
        """
        If OTP code is wrong, verification should fail with 400
        and email_verified should remain False.
        """
        user, reg_resp = self._register_user()

        otp = self._get_latest_otp(user)
        self.assertIsNotNone(otp)

        verify_url = reverse("api:auth-verify-otp")
        bad_payload = {
            "user_id": user.id,
            "code": "000000",  # definitely wrong
        }
        resp = self.client.post(verify_url, bad_payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)

        profile = UserProfile.objects.get(user=user)
        self.assertFalse(profile.email_verified)