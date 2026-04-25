import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory

from propertylist_app.models import Notification
from propertylist_app.api.serializers import NotificationSerializer


User = get_user_model()


@pytest.mark.django_db
def test_message_notification_deep_link_thread():
    user = User.objects.create_user(username="u1", password="pass")

    from propertylist_app.models import MessageThread

    thread = MessageThread.objects.create()

    notif = Notification.objects.create(
        user=user,
        type="message",
        thread=thread,
    )

    data = NotificationSerializer(notif).data
    assert data["deep_link"] == f"/app/threads/{thread.id}"


@pytest.mark.django_db
def test_tenancy_notification_deep_link():
    user = User.objects.create_user(username="u2", password="pass")

    notif = Notification.objects.create(
        user=user,
        type="tenancy_proposed",
        target_type="tenancy",
        target_id=5,
    )

    data = NotificationSerializer(notif).data
    assert data["deep_link"] == "/app/tenancies/5"


@pytest.mark.django_db
def test_review_notification_deep_link():
    user = User.objects.create_user(username="u3", password="pass")

    notif = Notification.objects.create(
        user=user,
        type="review_available",
        target_type="tenancy_review",
        target_id=9,
    )

    data = NotificationSerializer(notif).data
    assert data["deep_link"] == "/app/tenancies/9/reviews"


@pytest.mark.django_db
def test_still_living_notification_deep_link():
    user = User.objects.create_user(username="u4", password="pass")

    notif = Notification.objects.create(
        user=user,
        type="tenancy_still_living_check",
        target_type="still_living_check",
        target_id=11,
    )

    data = NotificationSerializer(notif).data
    assert data["deep_link"] == "/app/tenancies/11?tab=still-living"


@pytest.mark.django_db
def test_tenancy_extension_notification_deep_link():
    user = User.objects.create_user(username="u5", password="pass")

    notif = Notification.objects.create(
        user=user,
        type="tenancy_extension_proposed",
        target_type="tenancy_extension",
        target_id=14,
    )

    data = NotificationSerializer(notif).data
    assert data["deep_link"] == "/app/tenancies/14?tab=extension"


@pytest.mark.django_db
def test_default_fallback_deep_link():
    user = User.objects.create_user(username="u6", password="pass")

    notif = Notification.objects.create(
        user=user,
        type="unknown_type",
    )

    data = NotificationSerializer(notif).data
    assert data["deep_link"] == "/app/inbox"