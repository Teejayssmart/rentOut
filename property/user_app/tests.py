# user_app/tests.py
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class RegisterTestCase(APITestCase):
    def test_register(self):
        data = {
            "username": "testcase",
            "email": "testcase@example.com",
            "password": "NewPassword@123",
            # include any fields your register serializer requires:
            "password2": "NewPassword@123",
            "terms_accepted": True,
            "terms_version": "v1",
            "role": "seeker",
        }

        response = self.client.post(reverse("v1:auth-register"), data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
