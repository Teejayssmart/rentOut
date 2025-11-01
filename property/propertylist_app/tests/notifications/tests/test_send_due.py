from django.contrib.auth.models import User
from django.utils import timezone
from notifications.models import NotificationTemplate, OutboundNotification, NotificationPreference
from notifications.tasks import send_due_notifications

def test_send_due_notifications_sends_email(db, mailoutbox):
    u = User.objects.create_user("u1", email="u1@example.com", password="x")
    NotificationPreference.objects.create(user=u, email_enabled=True)
    NotificationTemplate.objects.create(key="listing_expiring", subject="Expiring", body="Hello {{ username }}")
    OutboundNotification.objects.create(
        user=u, channel="email", template_key="listing_expiring", scheduled_for=timezone.now()
    )
    res = send_due_notifications()
    assert res["sent"] == 1
    assert len(mailoutbox) == 1
    assert "Expiring" in mailoutbox[0].subject
