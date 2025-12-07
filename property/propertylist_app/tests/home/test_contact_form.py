from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from propertylist_app.models import ContactMessage


class ContactFormTests(APITestCase):
    def setUp(self):
        self.url = reverse("api:contact-create")

    def test_contact_valid_submission_creates_message(self):
        payload = {
            "name": "Jane Tester",
            "email": "jane@example.com",
            "subject": "Question about listings",
            "message": "Hi, I would like to know more about your service.",
        }

        resp = self.client.post(self.url, data=payload, format="json")

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ContactMessage.objects.count(), 1)

        msg = ContactMessage.objects.first()
        self.assertEqual(msg.name, payload["name"])
        self.assertEqual(msg.email, payload["email"])
        self.assertEqual(msg.subject, payload["subject"])
        self.assertEqual(msg.message, payload["message"])

    def test_contact_requires_all_fields(self):
        # missing email + message
        payload = {
            "name": "No Email",
            "subject": "Empty body",
        }

        resp = self.client.post(self.url, data=payload, format="json")

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("field_errors", resp.data)
        self.assertIn("email", resp.data["field_errors"])
        self.assertIn("message", resp.data["field_errors"])


    def test_contact_does_not_require_authentication(self):
        payload = {
            "name": "Anon User",
            "email": "anon@example.com",
            "subject": "Support",
            "message": "I am not logged in but need help.",
        }

        resp = self.client.post(self.url, data=payload, format="json")

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
