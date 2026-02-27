from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        # Make celery-beat schedule self-healing after deploy/migrate
        try:
            from django.db.models.signals import post_migrate
            post_migrate.connect(ensure_notification_periodic_tasks, sender=self)
        except Exception:
            # Never block startup
            pass


def ensure_notification_periodic_tasks(**kwargs):
    """
    Guarantee PeriodicTask for sending due notifications exists and always targets
    the same queue/routing_key so tasks don't get stuck as 'queued' forever.
    """
    try:
        from django.utils import timezone
        from django_celery_beat.models import CrontabSchedule, PeriodicTask, PeriodicTasks

        cron, _ = CrontabSchedule.objects.get_or_create(
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
                "crontab": cron,
                "enabled": True,
                "queue": "celery",
                "routing_key": "celery",
                "exchange": None,
            },
        )

        # Force beat to reload DB schedule
        PeriodicTasks.objects.update_or_create(
            ident=1, defaults={"last_update": timezone.now()}
        )
    except Exception:
        # Never block migrations/startup
        pass