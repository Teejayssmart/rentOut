# notifications/apps.py
from __future__ import annotations

from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate


def ensure_notification_periodic_tasks(**kwargs) -> None:
    """
    Create/repair the django-celery-beat PeriodicTask rows for notifications.

    IMPORTANT:
    - We set queue + routing_key explicitly, otherwise tasks can sit "queued" forever
      depending on how the worker is consuming.
    - We run this on post_migrate to avoid DB queries during app initialization.
    """
    from django.utils import timezone
    from django_celery_beat.models import CrontabSchedule, PeriodicTask, PeriodicTasks

    tz = getattr(settings, "TIME_ZONE", "UTC")

    # Every minute
    every_minute, _ = CrontabSchedule.objects.get_or_create(
        minute="*",
        hour="*",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone=tz,
    )

    PeriodicTask.objects.update_or_create(
        name="send-due-notifications-every-minute",
        defaults={
            "task": "notifications.tasks.send_due_notifications",
            "crontab": every_minute,
            "enabled": True,
            "queue": "celery",
            "routing_key": "celery",
            "exchange": None,
            "args": "[]",
            "kwargs": "{}",
        },
    )

    # OPTIONAL: keep/repair your daily listing expiry task (if you want it here too)
    # daily_7am, _ = CrontabSchedule.objects.get_or_create(
    #     minute="0", hour="7", day_of_week="*", day_of_month="*", month_of_year="*", timezone=tz
    # )
    # PeriodicTask.objects.update_or_create(
    #     name="notify-listing-expiring-daily-7am",
    #     defaults={
    #         "task": "notifications.tasks.notify_listing_expiring",
    #         "crontab": daily_7am,
    #         "enabled": True,
    #         "queue": "celery",
    #         "routing_key": "celery",
    #         "exchange": None,
    #         "args": "[]",
    #         "kwargs": "{}",
    #     },
    # )

    # Make beat reload schedule immediately
    PeriodicTasks.objects.update_or_create(
        ident=1,
        defaults={"last_update": timezone.now()},
    )


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self) -> None:
        post_migrate.connect(ensure_notification_periodic_tasks, sender=self)