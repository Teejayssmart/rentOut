import pytest
from django.urls import reverse
from rest_framework import status

from propertylist_app.models import MessageThread, UserProfile, Notification


@pytest.mark.django_db
def test_new_message_creates_notification_for_recipient_when_enabled(api_client, user, user2):
    # user sends, user2 receives
    api_client.force_authenticate(user=user)

    # recipient preferences enabled
    prof2, _ = UserProfile.objects.get_or_create(user=user2)
    prof2.notify_messages = True
    prof2.save(update_fields=["notify_messages"])

    thread = MessageThread.objects.create()
    thread.participants.set([user, user2])

    url = reverse("api:thread-messages", kwargs={"thread_id": thread.id})
    res = api_client.post(url, {"body": "hello"}, format="json")

    assert res.status_code in [status.HTTP_201_CREATED, status.HTTP_200_OK]

    assert Notification.objects.filter(user=user2, type="message", title="New message").count() == 1
    # sender should not get notified
    assert Notification.objects.filter(user=user, type="message", title="New message").count() == 0


@pytest.mark.django_db
def test_new_message_does_not_create_notification_when_disabled(api_client, user, user2):
    api_client.force_authenticate(user=user)

    prof2, _ = UserProfile.objects.get_or_create(user=user2)
    prof2.notify_messages = False
    prof2.save(update_fields=["notify_messages"])

    thread = MessageThread.objects.create()
    thread.participants.set([user, user2])

    url = url = reverse("api:thread-messages", kwargs={"thread_id": thread.id})
    res = api_client.post(url, {"body": "hello"}, format="json")

    assert res.status_code in [status.HTTP_201_CREATED, status.HTTP_200_OK]
    assert Notification.objects.filter(user=user2, type="message", title="New message").count() == 0
