from unittest.mock import patch

from django.test import TestCase

from propertylist_app.api.serializers import RegistrationSerializer


class RegistrationPasswordPolicyTests(TestCase):
    def make_payload(self, password: str, password2: str = None):
        """
        Base valid payload for RegistrationSerializer.
        Only the password values change per test.
        """
        if password2 is None:
            password2 = password

        return {
            "username": "testuser",
            "email": "test@example.com",
            "password": password,
            "password2": password2,
            "first_name": "Test",
            "last_name": "User",
            "role": "seeker",
            "terms_accepted": True,
            "terms_version": "v1",
            "marketing_consent": False,
        }

    def assert_password_error(self, password: str):
        data = self.make_payload(password)
        serializer = RegistrationSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        # all complexity errors should be attached to the "password" field
        self.assertIn("password", serializer.errors)
        self.assertNotIn("non_field_errors", serializer.errors)

    def test_rejects_password_shorter_than_8_chars(self):
        self.assert_password_error("Aa1!")

    def test_rejects_password_without_lowercase(self):
        self.assert_password_error("PASSWORD1!")

    def test_rejects_password_without_uppercase(self):
        self.assert_password_error("password1!")

    def test_rejects_password_without_digit(self):
        self.assert_password_error("Password!")

    def test_rejects_password_without_special_character(self):
        self.assert_password_error("Password1")

    @patch("propertylist_app.api.serializers.password_validation.validate_password")
    def test_accepts_valid_password_and_calls_django_validator(self, mock_validate):
        password = "GoodPass1!"
        data = self.make_payload(password)
        serializer = RegistrationSerializer(data=data)

        self.assertTrue(serializer.is_valid(), serializer.errors)

        user = serializer.save()
        self.assertIsNotNone(user.pk)

        # ensure Django's password validator was called
        mock_validate.assert_called_once_with(password)
