from __future__ import annotations
from typing import Optional
from propertylist_app.models import Notification, UserProfile
from django.conf import settings



def create_in_app_notification_if_allowed(
    *,
    user,
    notification_type: str,
    title: str,
    body: str,
    preference_field: str,
    audience: str = Notification.Audience.BOTH,
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
        audience=audience,
    )




def build_frontend_inbox_link(tab: str = "notifications") -> str:
    """
    Link that opens the frontend messages page.

    Authentication is handled by the frontend:
    - signed-in users continue directly;
    - signed-out users are redirected through login and returned here.
    """
    base = (getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/")

    if not base:
        return "/messages"

    return f"{base}/messages"