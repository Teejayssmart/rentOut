# property/propertylist_app/tests/test_security.py
from unittest.mock import patch
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.core.cache import cache
import pytest

User = get_user_model()


def _auth_headers(ip="127.0.0.10"):
    # DRF identifies anonymous requests by REMOTE_ADDR for throttling.
    return {"REMOTE_ADDR": ip}


@override_settings(
    # Keep your lockout logic easy to trigger in tests
    LOGIN_FAIL_LIMIT=3,
    LOGIN_LOCKOUT_SECONDS=60,
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": (
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ),
        "DEFAULT_PERMISSION_CLASSES": (
            "rest_framework.permissions.IsAuthenticatedOrReadOnly",
        ),
        "DEFAULT_FILTER_BACKENDS": (
            "django_filters.rest_framework.DjangoFilterBackend",
            "rest_framework.filters.OrderingFilter",
        ),
        "DEFAULT_THROTTLE_CLASSES": (
            "rest_framework.throttling.AnonRateThrottle",
            "rest_framework.throttling.UserRateThrottle",
            "rest_framework.throttling.ScopedRateThrottle",
        ),
        # Keep "login" throttle high so we’re testing YOUR lockout logic, not DRF throttling
        "DEFAULT_THROTTLE_RATES": {
            "anon": "100/hour",
            "user": "200/hour",
            "login": "100/hour",
        },
        "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    },
)
class TestLoginLockout(APITestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="lockuser", email="lock@example.com", password="goodpass123"
        )
        self.login_url = reverse("v1:auth-login")

    def test_login_lockout_after_failures(self):
        # Exactly 3 wrong attempts -> 400s
        for i in range(3):
            r = self.client.post(
                self.login_url,
                {"username": "lockuser", "password": "WRONG"},
                format="json",
                **_auth_headers(),
            )
            self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, f"Attempt {i+1} should be 400")
        # 4th wrong -> 429 (locked)
        r4 = self.client.post(
            self.login_url,
            {"username": "lockuser", "password": "WRONG"},
            format="json",
            **_auth_headers(),
        )
        self.assertEqual(r4.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_success_clears_failures(self):
        # Stay under the lockout: only 1 wrong attempt
        self.client.post(
            self.login_url,
            {"username": "lockuser", "password": "WRONG"},
            format="json",
            **_auth_headers(),
        )
        ok = self.client.post(
            self.login_url,
            {"username": "lockuser", "password": "goodpass123"},
            format="json",
            **_auth_headers(),
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.content)
        self.assertIn("access", ok.data)


class TestRegisterThrottle(APITestCase):
    @override_settings(
        ENABLE_CAPTCHA=False,  # keep CAPTCHA out of this test
        REST_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": (
                "rest_framework_simplejwt.authentication.JWTAuthentication",
            ),
            "DEFAULT_PERMISSION_CLASSES": (
                "rest_framework.permissions.IsAuthenticatedOrReadOnly",
            ),
            "DEFAULT_FILTER_BACKENDS": (
                "django_filters.rest_framework.DjangoFilterBackend",
                "rest_framework.filters.OrderingFilter",
            ),
            "DEFAULT_THROTTLE_CLASSES": (
                "rest_framework.throttling.AnonRateThrottle",
                "rest_framework.throttling.UserRateThrottle",
                "rest_framework.throttling.ScopedRateThrottle",
            ),
            # Use anon throttle 2/hour so we don't depend on a scope existing
            "DEFAULT_THROTTLE_RATES": {"anon": "2/hour", "user": "200/hour"},
            "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
        },
    )
    

    @pytest.mark.xfail(reason="Throttle counters isolated per test run (cache randomised)")
    def test_register_anon_throttle_hits_limit(self):
        client = APIClient()
        url = reverse("v1:auth-register")

        # Two creates allowed
        for i in range(2):
            r = client.post(
                url,
                {"username": f"user{i}", "email": f"user{i}@example.com", "password": "pass12345"},
                format="json",
                **_auth_headers(ip="203.0.113.10"),
            )
            self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)

        # Third from same IP -> 429
        r3 = client.post(
            url,
            {"username": "user2", "email": "user2@example.com", "password": "pass12345"},
            format="json",
            **_auth_headers(ip="203.0.113.10"),
        )
        self.assertEqual(r3.status_code, status.HTTP_429_TOO_MANY_REQUESTS, r3.content)


class TestCaptcha(APITestCase):
    def setUp(self):
        self.client = APIClient()

    @override_settings(ENABLE_CAPTCHA=True)
    @patch("propertylist_app.api.views.verify_captcha", return_value=False)  # patch where it's called
    def test_login_captcha_fail_blocks(self, mocked_verify):
        url = reverse("v1:auth-login")
        resp = self.client.post(
            url,
            {"username": "any", "password": "any", "captcha_token": "bad-token"},
            format="json",
            **_auth_headers(ip="198.51.100.55"),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("CAPTCHA", (resp.data.get("detail") or "").upper())

    @override_settings(ENABLE_CAPTCHA=True)
    @patch("propertylist_app.api.views.verify_captcha", return_value=True)   # patch where it's called
    def test_register_captcha_success_allows(self, mocked_verify):
        url = reverse("v1:auth-register")
        resp = self.client.post(
            url,
            {"username": "captchauser", "email": "cap@example.com", "password": "pass12345", "captcha_token": "ok"},
            format="json",
            **_auth_headers(ip="198.51.100.55"),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)


class TestMessagingThrottle(APITestCase):
    @override_settings(
        REST_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": (
                "rest_framework_simplejwt.authentication.JWTAuthentication",
            ),
            "DEFAULT_PERMISSION_CLASSES": (
                "rest_framework.permissions.IsAuthenticatedOrReadOnly",
            ),
            "DEFAULT_FILTER_BACKENDS": (
                "django_filters.rest_framework.DjangoFilterBackend",
                "rest_framework.filters.OrderingFilter",
            ),
            "DEFAULT_THROTTLE_CLASSES": (
                "rest_framework.throttling.AnonRateThrottle",
                "rest_framework.throttling.UserRateThrottle",
                "rest_framework.throttling.ScopedRateThrottle",
            ),
            # Use simple per-user throttle: 2 posts/hour
            "DEFAULT_THROTTLE_RATES": {"anon": "100/hour", "user": "2/hour"},
            "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
        }
    )
    def test_message_user_throttle_hits_limit(self):
        u1 = User.objects.create_user(username="alice", email="a@x.com", password="pass12345")
        u2 = User.objects.create_user(username="bob", email="b@x.com", password="pass12345")

        client = APIClient()
        client.force_authenticate(user=u1)

        from propertylist_app.models import MessageThread
        thread = MessageThread.objects.create()
        thread.participants.set([u1, u2])

        url = reverse("v1:thread-messages", kwargs={"thread_id": thread.pk})

        # Two allowed
        for i in range(2):
            r = client.post(
                url,
                {"body": f"Hi {i}"},
                format="json",
                **_auth_headers(ip="192.0.2.20"),
            )
            assert r.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), r.content

        # Third should hit per-user throttle 2/hour -> 429
        r3 = client.post(
            url,
            {"body": "spam"},
            format="json",
            **_auth_headers(ip="192.0.2.20"),
        )
        self.assertEqual(r3.status_code, status.HTTP_429_TOO_MANY_REQUESTS, r3.content)
