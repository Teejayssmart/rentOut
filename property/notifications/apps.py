# notifications/apps.py
from __future__ import annotations

from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.dispatch import receiver


def ensure_notification_periodic_tasks(using: str | None = None) -> None:
    """
    Ensure django-celery-beat PeriodicTask rows exist and are routed correctly.

    IMPORTANT:
    - This function touches the DB, so DO NOT call it directly from AppConfig.ready().
    - It is triggered via post_migrate (safe time to query DB).
    """
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    # Run every minute (timezone-aware schedule)
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
            # ✅ this is what was missing and caused “stuck queued”
            "queue": "celery",
            "routing_key": "celery",
            "exchange": None,
        },
    )


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self) -> None:
        # Connect signals only (NO DB queries here)
        post_migrate.connect(run_notifications_post_migrate, sender=self)


@receiver(post_migrate)
def run_notifications_post_migrate(sender, using=None, **kwargs) -> None:
    # Safe place to touch DB.
    # Runs after migrations and ensures periodic tasks exist correctly.
    ensure_notification_periodic_tasks(using=using)