from django.apps import AppConfig
# from django.db.models.signals import post_migrate
# from django.utils import timezone










class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        # Ensure celery-beat PeriodicTask config doesn't drift (queue/routing_key becoming None)
        try:
            from django.db.models.signals import post_migrate
            post_migrate.connect(_ensure_periodic_tasks, sender=self)
        except Exception:
            # Never block startup
            pass


def _ensure_periodic_tasks(**kwargs):
    try:
        from django.utils import timezone
        from django_celery_beat.models import CrontabSchedule, PeriodicTask, PeriodicTasks

        # every minute
        cron, _ = CrontabSchedule.objects.get_or_create(
            minute="*",
            hour="*",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone="Europe/London",
        )

        t, _ = PeriodicTask.objects.update_or_create(
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

        # bump schedule version so beat reloads
        PeriodicTasks.objects.update_or_create(
            ident=1, defaults={"last_update": timezone.now()}
        )
    except Exception:
        # Never block migrations/startup
        pass