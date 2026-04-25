import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "property.settings")

from celery import Celery
from celery.schedules import crontab

app = Celery("property")
app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks([
    "propertylist_app",
    "propertylist_app.notifications",
])

# Register compatibility bridge task names.
app.conf.imports = tuple(app.conf.get("imports", ())) + ("notifications.tasks",)

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
        "schedule": crontab(minute=0),
        "args": (24,),
    },
    "notify-completed-viewings-hourly": {
        "task": "propertylist_app.notifications.tasks.notify_completed_viewings",
        "schedule": crontab(minute=0),
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
    "refresh-tenancy-status-and-review-windows-daily": {
        "task": "propertylist_app.tasks.task_refresh_tenancy_status_and_review_windows",
        "schedule": 60 * 60 * 24,
    },
}