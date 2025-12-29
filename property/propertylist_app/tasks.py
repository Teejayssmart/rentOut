from django.utils import timezone
from django.contrib.auth import get_user_model

from propertylist_app.models import UserProfile



# property/propertylist_app/tasks.py

# Try the real Celery decorator; if Celery isn't available (e.g., in tests),
# fall back to a shim so `.delay()` still calls the function synchronously.
try:
    from celery import shared_task  # real Celery
except Exception:  # pragma: no cover
    def shared_task(*dargs, **dkwargs):
        def decorator(func):
            class _TaskShim:
                def delay(self, *a, **kw):
                    return func(*a, **kw)

                def __call__(self, *a, **kw):
                    return func(*a, **kw)

            return _TaskShim()
        return decorator

from propertylist_app.services.tasks import send_new_message_email, expire_paid_listings

# ✅ IMPORTANT: import nested tasks so Celery registers them at worker startup
from propertylist_app.notifications.tasks import notify_completed_viewings  # noqa: F401


@shared_task(name="propertylist_app.send_new_message_email")
def task_send_new_message_email(message_id: int) -> int:
    return send_new_message_email(message_id)


@shared_task(name="propertylist_app.expire_paid_listings")
def task_expire_paid_listings() -> int:
    return expire_paid_listings()






@shared_task(name="propertylist_app.delete_scheduled_accounts")
def task_delete_scheduled_accounts() -> int:
    """
    Permanently delete users whose accounts are scheduled for deletion
    and the scheduled time has arrived.
    Returns the number of users deleted.
    """
    now = timezone.now()

    profiles = (
        UserProfile.objects
        .filter(pending_deletion_scheduled_for__isnull=False)
        .filter(pending_deletion_scheduled_for__lte=now)
        .select_related("user")
    )

    deleted = 0
    UserModel = get_user_model()

    for profile in profiles:
        user = profile.user
        if not user:
            # safety: clean up dangling profile flags
            profile.pending_deletion_requested_at = None
            profile.pending_deletion_scheduled_for = None
            profile.save(update_fields=["pending_deletion_requested_at", "pending_deletion_scheduled_for"])
            continue

        # hard delete user (cascades to related models)
        UserModel.objects.filter(pk=user.pk).delete()
        deleted += 1

    return deleted
