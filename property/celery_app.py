# property/celery_app.py
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "property.settings")

app = Celery("property")

# Read CELERY_* settings from Django settings.py (namespace)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py in installed apps
app.autodiscover_tasks([
    "propertylist_app",
    "propertylist_app.notifications",
])

# (Optional) Define schedules here if you prefer centralised config
# NOTE: You can also keep schedules in settings.py; choose ONE place.
# Beat schedule (single source of truth — do NOT also define in settings.py)
app.conf.beat_schedule = {
    # Notifications
    "send-due-notifications-every-minute": {
        "task": "notifications.tasks.send_due_notifications",
        "schedule": crontab(minute="*"),
    },
    "notify-listing-expiring-daily-7am": {
        "task": "notifications.tasks.notify_listing_expiring",
        "schedule": crontab(hour=7, minute=0),
    },
    "notify-upcoming-bookings-hourly": {
        "task": "propertylist_app.services.tasks.notify_upcoming_bookings",
        "schedule": crontab(minute=0),  # every hour
        "args": (24,),
    },
    "notify-completed-viewings-hourly": {
        "task": "propertylist_app.notifications.tasks.notify_completed_viewings",
        "schedule": crontab(minute=0),  # every hour
    },

    # Listings & accounts
    "expire-paid-listings-daily-03:00": {
        "task": "propertylist_app.expire_paid_listings",
        "schedule": crontab(hour=3, minute=0),
    },
    "delete-scheduled-accounts-daily-03:10": {
        "task": "propertylist_app.delete_scheduled_accounts",
        "schedule": crontab(hour=3, minute=10),
    },

    # Reviews
    "refresh-room-ratings-nightly-02:30": {
        "task": "propertylist_app.refresh_room_ratings_nightly",
        "schedule": crontab(hour=2, minute=30),
    },

    # Tenancy sweeps
    "tenancy-prompts-sweep-daily-03:20": {
        "task": "propertylist_app.tasks.task_tenancy_prompts_sweep",
        "schedule": crontab(hour=3, minute=20),
    },
    "refresh_tenancy_status_and_review_windows_daily": {
        "task": "propertylist_app.tasks.task_refresh_tenancy_status_and_review_windows",
        "schedule": 60 * 60 * 24,  # daily
    },
}
