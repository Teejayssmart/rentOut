"""
Bridge module so imports like `from notifications.tasks import ...` keep working.

Your actual implementations live in:
- propertylist_app.notifications.tasks
"""

from propertylist_app.notifications.tasks import (  # noqa: F401
    send_due_notifications,
    notify_listing_expiring,
)
