from __future__ import annotations

import json
from django.apps import AppConfig
from django.db.models.signals import post_migrate


def ensure_notification_periodic_tasks(sender, **kwargs):
    """
    Create/repair celery beat PeriodicTask rows.

    IMPORTANT:
    - Do NOT run DB writes in AppConfig.ready() directly.
    - Always set queue/routing_key so beat routes to the worker queue.
    """
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="*",
        hour="*",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Europe/London",
    )

    PeriodicTask.objects.update_or_create(
        name="send-due-notifications-every-minute",
        defaults={
            "task": "notifications.tasks.send_due_notifications",
            "crontab": schedule,
            "enabled": True,
            "queue": "celery",
            "routing_key": "celery",
            "exchange": None,
            "kwargs": json.dumps({}),
        },
    )

    # OPTIONAL: if you also schedule notify_listing_expiring in DB
    # (If you already manage it elsewhere, remove this block)
    PeriodicTask.objects.update_or_create(
        name="notify-listing-expiring-daily-7am",
        defaults={
            "task": "notifications.tasks.notify_listing_expiring",
            "crontab": CrontabSchedule.objects.get_or_create(
                minute="0",
                hour="7",
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
                timezone="Europe/London",
            )[0],
            "enabled": True,
            "queue": "celery",
            "routing_key": "celery",
            "exchange": None,
            "kwargs": json.dumps({}),
        },
    )


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        # Safe place to do DB writes: after migrations
        post_migrate.connect(ensure_notification_periodic_tasks, sender=self)