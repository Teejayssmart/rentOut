# property/settings_test.py
from .settings import *  # noqa

# Make tests predictable
DEBUG = True
ENABLE_CAPTCHA = False  # tests toggle this explicitly where needed

# Faster hashing for tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# In-memory email + cache
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "throttle-cache",  # required by test_environment_config.py
    }
}

# Media to a tmp dir (so photo tests don’t touch your real media)
import os, tempfile
MEDIA_ROOT = os.path.join(tempfile.gettempdir(), "test_media_rentout")
os.makedirs(MEDIA_ROOT, exist_ok=True)

# DRF: make default throttles generous so they don’t trip unrelated tests.
# (Tests that *expect* throttling use override_settings to set narrow rates.)
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # keep whatever you already set
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # Baselines; tests narrow these when needed:
        "user": "10000/hour",
        "anon": "10000/hour",

        # Scopes used in your views/tests:
        "login": "10000/hour",
        "register": "10000/hour",
        "register_anon": "10000/hour",
        "review-list": "10000/hour",
        "review-create": "10000/hour",
        "review-detail": "10000/hour",
        "password-reset": "10000/hour",
        "password-reset-confirm": "10000/hour",
        "message_user": "10000/hour",
        "report-create": "10000/hour",
        "moderation": "10000/hour",
    },
}

# Stripe keys safe defaults
STRIPE_SECRET_KEY = "sk_test_dummy"
STRIPE_PUBLISHABLE_KEY = "pk_test_dummy"
STRIPE_WEBHOOK_SECRET = "whsec_dummy"

# Site url used by payments
SITE_URL = "http://testserver"

# Keep test DB speedy
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
