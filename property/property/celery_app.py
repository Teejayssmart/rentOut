# property/celery_app.py  (INSIDE the Django package folder)
"""
Wrapper so BOTH imports work:
 - import property.celery_app
 - import celery_app
"""
try:
    from celery_app import app as app  # re-export top-level app
except Exception:
    import os
    from celery import Celery
    from celery.schedules import crontab

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "property.settings")
    app = Celery("property")
    app.config_from_object("django.conf:settings", namespace="CELERY")
    app.autodiscover_tasks()
    app.conf.beat_schedule = {
        "expire-paid-listings-daily": {
            "task": "propertylist_app.tasks.task_expire_paid_listings",
            "schedule": crontab(minute=0, hour=3),
        },
    }
