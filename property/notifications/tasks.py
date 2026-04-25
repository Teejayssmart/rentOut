"""
Bridge module so old task paths keep working.

Celery Beat uses:
- notifications.tasks.send_due_notifications
- notifications.tasks.notify_listing_expiring
"""

from propertylist_app.notifications.tasks import (
    send_due_notifications,
    notify_listing_expiring,
)

__all__ = (
    "send_due_notifications",
    "notify_listing_expiring",
)