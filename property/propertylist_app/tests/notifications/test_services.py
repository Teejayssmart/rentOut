import pytest
from unittest.mock import patch
from django.contrib.auth import get_user_model
from notifications.models import NotificationTemplate, NotificationPreference, OutboundNotification, DeliveryAttempt
from notifications.services import NotificationService

pytestmark = pytest.mark.django_db

def setup_user(email="u@example.com", username="u1"):
    User = get_user_model()
    return User.objects.create_user(username=username, email=email, password="x")

def test_render_and_queue_and_deliver_email_success():
    u = setup_user()
    tpl = NotificationTemplate.objects.create(
        key="welcome",
        channel="email",
        subject="Hello {{ user.first_name }}",
        body="Hi {{ user.first_name }}!",
        is_active=True,
    )
    n = NotificationService.queue(user=u, template_key="welcome", context={"user": {"first_name": "Ada"}})
    assert isinstance(n, OutboundNotification)

    with patch("notifications.services.send_mail", return_value=1) as sm:
        NotificationService.deliver(n)
    n.refresh_from_db()
    assert n.status == OutboundNotification.STATUS_SENT
    assert DeliveryAttempt.objects.filter(notification=n, success=True).exists()
    sm.assert_called_once()

def test_deliver_skips_when_email_pref_disabled():
    u = setup_user()
    NotificationPreference.objects.create(user=u, email_enabled=False)
    NotificationTemplate.objects.create(
        key="any",
        channel="email",
        subject="S",
        body="B",
        is_active=True,
    )
    n = NotificationService.queue(user=u, template_key="any", context={})
    with patch("notifications.services.send_mail", return_value=1) as sm:
        NotificationService.deliver(n)
    n.refresh_from_db()
    assert n.status == OutboundNotification.STATUS_SKIPPED
    assert not DeliveryAttempt.objects.filter(notification=n).exists()
    sm.assert_not_called()

def test_deliver_fails_when_template_missing():
    u = setup_user()
    n = NotificationService.queue(user=u, template_key="missing.key", context={})
    NotificationService.deliver(n)
    n.refresh_from_db()
    assert n.status == OutboundNotification.STATUS_FAILED
    assert "Template not found" in (n.error or "")
