# property/__init__.py
# Ensure Celery app is loaded when Django starts.
from .celery_app import app as celery_app  # noqa: F401

__all__ = ("celery_app",)
