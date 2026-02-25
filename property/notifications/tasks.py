# notifications/tasks.py
"""
Bridge module so imports like `from notifications.tasks import ...` keep working.

We also register Celery tasks under the short dotted names:
- notifications.tasks.send_due_notifications
- notifications.tasks.notify_listing_expiring
"""

# notifications/tasks.py
from celery import shared_task
from propertylist_app.notifications.tasks import (
    send_due_notifications as _impl_send_due_notifications,
    notify_listing_expiring as _impl_notify_listing_expiring,
)

@shared_task(name="notifications.tasks.send_due_notifications")
def send_due_notifications():
    return _impl_send_due_notifications()

@shared_task(name="notifications.tasks.notify_listing_expiring")
def notify_listing_expiring():
    return _impl_notify_listing_expiring()