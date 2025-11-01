# property/propertylist_app/tests/config/test_environment_config.py
import os
import importlib
import pytest
from django.conf import settings
from django.core.cache import cache



@pytest.mark.django_db
def test_email_backend_is_console_or_locmem_backend():
    """
    In dev it might be console; in tests Django/pytest often forces locmem.
    Accept either to avoid brittle failures across environments.
    """
    assert settings.EMAIL_BACKEND in {
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
    }


def test_celery_urls_are_redis_like():
    """
    We don't require Redis process to be running in tests; we just ensure
    the config is set to use redis:// URLs as intended.
    """
    assert isinstance(settings.CELERY_BROKER_URL, str)
    assert settings.CELERY_BROKER_URL.startswith("redis://")

    assert isinstance(settings.CELERY_RESULT_BACKEND, str)
    assert settings.CELERY_RESULT_BACKEND.startswith("redis://")


def test_celery_app_imports_and_has_basic_attrs():
    """
    Support both placements:
      - top-level celery_app.py  (import 'celery_app')
      - package  property/celery_app.py  (import 'property.celery_app')

    We only sanity-check that an object named 'app' exists and, if it is a
    Celery instance, that its .main is the expected project name.
    """
    mod = None
    tried = []

    for name in ("property.celery_app", "celery_app"):
        try:
            mod = importlib.import_module(name)
            break
        except ModuleNotFoundError:
            tried.append(name)

    if mod is None:
        pytest.fail(f"Could not import Celery app from any of: {tried}")

    assert hasattr(mod, "app"), "Expected module to expose 'app'"

    app = getattr(mod, "app", None)
    # If a real Celery app is present, it usually has .main set to project name.
    main = getattr(app, "main", None)
    # We don't hard-fail if None (e.g., in shims); just sanity-check when present.
    if main is not None:
        assert main in {"property"}


@pytest.mark.xfail(reason="Cache location randomised per test run to prevent state pollution")
def test_cache_backend_is_locmem_default_and_named_location():
    """
    We expect the default cache to be in-memory (fast, ephemeral) for tests.
    Location name helps avoid clashes if multiple caches are used in-process.
    """
    default_cache = settings.CACHES.get("default", {})
    assert default_cache.get("BACKEND") == "django.core.cache.backends.locmem.LocMemCache"
    assert default_cache.get("LOCATION") == "throttle-cache"


def test_media_root_exists_and_is_writable(tmp_path):
    """
    MEDIA_ROOT should exist (or be creatable) and be writable by the app.
    We'll create a temp file in there and remove it immediately.
    """
    media_root = settings.MEDIA_ROOT
    assert media_root, "MEDIA_ROOT must be set"
    os.makedirs(media_root, exist_ok=True)

    test_file_path = os.path.join(media_root, ".__writability_probe__")
    try:
        with open(test_file_path, "wb") as f:
            f.write(b"ok")
        assert os.path.exists(test_file_path)
    finally:
        try:
            os.remove(test_file_path)
        except FileNotFoundError:
            pass


def test_allowed_hosts_contains_local_devs():
    """
    Helpful sanity check for local/dev URLs used in your settings.
    We don't enforce exact lists, just that common dev hosts are allowed.
    """
    hosts = set(settings.ALLOWED_HOSTS or [])
    assert {"127.0.0.1", "localhost"} & hosts
