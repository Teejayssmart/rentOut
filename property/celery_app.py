# property/celery_app.py
import os

# Always point Celery (or our shim) at Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "property.settings")

# Try the real Celery first; fall back to a no-op shim in test/dev envs
try:
    from celery import Celery  # real Celery
    from celery.schedules import crontab
    HAVE_CELERY = True
except Exception:  # Celery not installed — provide a stub
    Celery = None
    crontab = None
    HAVE_CELERY = False

if HAVE_CELERY:
    # Real Celery app
    app = Celery("property")
    app.config_from_object("django.conf:settings", namespace="CELERY")
    app.autodiscover_tasks()

    # Optional: Celery Beat schedule (safe even if Beat isn’t running)
    app.conf.beat_schedule = {
        "expire-paid-listings-daily": {
            "task": "propertylist_app.tasks.task_expire_paid_listings",
            "schedule": crontab(minute=0, hour=3),
        },
    }
else:
    # Minimal shim so importing this module never crashes tests
    class _DummyCelery:
        main = "property"
        conf = type("Cfg", (), {"beat_schedule": {}})()

        def config_from_object(self, *args, **kwargs):
            pass

        def autodiscover_tasks(self, *args, **kwargs):
            pass

    app = _DummyCelery()
