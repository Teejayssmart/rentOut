from __future__ import annotations

from django.db import migrations
from django.utils import timezone


def upsert_send_due_notifications_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTasks = apps.get_model("django_celery_beat", "PeriodicTasks")

    # Every minute
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute="*",
        hour="*",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Europe/London",  # match what you already have in DB
    )

    # IMPORTANT: keep the task path consistent with what your worker registers.
    # You confirmed the worker lists: notifications.tasks.send_due_notifications
    task_path = "notifications.tasks.send_due_notifications"

    # Force correct routing so beat sends into the queue workers are consuming.
    defaults = {
        "task": task_path,
        "crontab": crontab,
        "enabled": True,
        "one_off": False,
        "queue": "celery",
        "routing_key": "celery",
        "exchange": None,
        "priority": None,
        "headers": {},
        "kwargs": "{}",
        "args": "[]",
        "description": "Auto-managed by migration: sends due OutboundNotification emails every minute.",
    }

    PeriodicTask.objects.update_or_create(
        name="send-due-notifications-every-minute",
        defaults=defaults,
    )

    # Nudge DatabaseScheduler to reload schedule immediately.
    PeriodicTasks.objects.update_or_create(
        ident=1,
        defaults={"last_update": timezone.now()},
    )


class Migration(migrations.Migration):

    dependencies = [
        # Keep your existing latest migration here, plus django_celery_beat dependency.
        # If Django auto-filled something else, keep it and add the django_celery_beat line below.
        ("notifications", "0001_initial"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),  # safe baseline for most installs
    ]

    operations = [
        migrations.RunPython(
            upsert_send_due_notifications_periodic_task,
            reverse_code=migrations.RunPython.noop,
        ),
    ]