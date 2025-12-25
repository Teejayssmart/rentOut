from __future__ import annotations
from typing import Optional
from propertylist_app.models import Notification, UserProfile
from urllib.parse import quote
from django.conf import settings



def create_in_app_notification_if_allowed(
    *,
    user,
    notification_type: str,
    title: str,
    body: str,
    preference_field: str,
) -> Optional[Notification]:
    """
    Creates an in-app Notification only if the user's profile preference allows it.
    preference_field examples:
      - "notify_messages"
      - "notify_confirmations"
      - "notify_reminders"
    """
    profile, _ = UserProfile.objects.get_or_create(user=user)

    allowed = bool(getattr(profile, preference_field, True))
    if not allowed:
        return None

    return Notification.objects.create(
        user=user,
        type=notification_type,
        title=title,
        body=body,
    )




def build_frontend_inbox_link(tab: str = "notifications") -> str:
    """
    Link that opens the app inbox. Frontend should:
    - if not logged in -> show login
    - after login -> redirect back here
    """
    base = (getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/")
    if not base:
        return "/app/inbox"

    # Example: https://rentout.co.uk/app/inbox?tab=notifications
    return f"{base}/app/inbox?tab={quote(tab)}"
