# property/celery_app.py
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "property.settings")

app = Celery("property")

# Read CELERY_* settings from Django settings.py (namespace)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py in installed apps
app.autodiscover_tasks()

# (Optional) Define schedules here if you prefer centralised config
# NOTE: You can also keep schedules in settings.py; choose ONE place.
app.conf.beat_schedule = {
    # Expire paid listings daily at 03:00
    "expire-paid-listings-daily": {
        "task": "propertylist_app.tasks.task_expire_paid_listings",
        "schedule": crontab(hour=3, minute=0),
    },
    # Queue “listing expiring in N days” reminders daily at 07:00
    "queue-expiry-reminders-daily": {
        "task": "notifications.tasks.notify_listing_expiring",
        "schedule": crontab(hour=7, minute=0),
        "options": {"queue": "emails"},
    },
    # Send due notifications every minute
    "send-due-notifications": {
        "task": "notifications.tasks.send_due_notifications",
        "schedule": crontab(),  # every minute
        "options": {"queue": "emails"},
    },
}
