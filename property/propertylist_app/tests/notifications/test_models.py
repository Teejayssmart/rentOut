import pytest
from django.contrib.auth import get_user_model
from notifications.models import (
    NotificationTemplate,
    NotificationPreference,
    OutboundNotification,
    DeliveryAttempt,
)

pytestmark = pytest.mark.django_db


def test_notification_template_create():
    tpl = NotificationTemplate.objects.create(
        key="message.new",
        channel="email",
        subject="Hi",
        body="Hello {{ user.first_name }}",
        is_active=True,
    )
    assert tpl.pk
    assert str(tpl) == "message.new (email)"


def test_notification_preference_default_true():
    User = get_user_model()
    u = User.objects.create_user(username="a", email="a@example.com", password="x")
    pref = NotificationPreference.objects.create(user=u)
    assert pref.email_enabled is True
    assert "Prefs for" in str(pref)


def test_outbound_notification_and_attempts():
    User = get_user_model()
    u = User.objects.create_user(username="b", email="b@example.com", password="x")
    n = OutboundNotification.objects.create(
        user=u, template_key="any.key", channel="email", context={}
    )
    assert n.status == OutboundNotification.STATUS_QUEUED

    att = DeliveryAttempt.objects.create(
        notification=n, provider="email", success=False, response="mock"
    )
    assert att.pk
