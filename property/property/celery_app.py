"""
Compatibility wrapper so BOTH imports work:

- import celery_app
- import property.celery_app
"""

from celery_app import app

__all__ = ("app",)