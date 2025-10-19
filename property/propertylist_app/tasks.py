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

@shared_task(name="propertylist_app.send_new_message_email")
def task_send_new_message_email(message_id: int) -> int:
    return send_new_message_email(message_id)

@shared_task(name="propertylist_app.expire_paid_listings")
def task_expire_paid_listings() -> int:
    return expire_paid_listings()
