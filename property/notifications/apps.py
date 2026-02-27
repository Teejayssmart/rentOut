from django.apps import AppConfig


def ensure_notification_periodic_tasks() -> None:
    """
    Make sure the beat PeriodicTask exists AND is routed to the 'celery' queue.

    This must be idempotent (safe to run multiple times).
    """
    try:
        from django.utils import timezone
        from django_celery_beat.models import CrontabSchedule, PeriodicTask, PeriodicTasks
    except Exception:
        return

    try:
        # run every minute (Europe/London like your admin shows)
        crontab, _ = CrontabSchedule.objects.get_or_create(
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
                "crontab": crontab,
                "enabled": True,
                # IMPORTANT: routing so it actually reaches the worker
                "queue": "celery",
                "routing_key": "celery",
                "exchange": None,
            },
        )

        # tell celery-beat DatabaseScheduler the schedule changed
        PeriodicTasks.objects.update_or_create(
            ident=1, defaults={"last_update": timezone.now()}
        )
    except Exception:
        # DB might not be migrated yet, don't crash startup
        return


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self) -> None:
        ensure_notification_periodic_tasks()