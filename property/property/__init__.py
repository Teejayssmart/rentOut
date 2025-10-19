# property/__init__.py

# Allow running without a Celery app present/working (e.g., in tests)
try:
    from .celery_app import app as celery_app  # noqa: F401
except Exception:  # pragma: no cover
    celery_app = None

__all__ = ("celery_app",)
