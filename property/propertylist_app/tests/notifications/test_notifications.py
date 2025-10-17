import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from propertylist_app.models import MessageThread, Message, Notification, RoomCategorie, Room

User = get_user_model()

@pytest.mark.django_db
def test_message_creates_notifications_and_mark_read_and_mark_all():
    # users
    a = User.objects.create_user(username="alice", password="pass123", email="a@example.com")
    b = User.objects.create_user(username="bob",   password="pass123", email="b@example.com")

    # thread
    t = MessageThread.objects.create()
    t.participants.add(a, b)

    # For URL that posts messages we need a room to use the "start-thread" or direct thread endpoint.
    # We’ll use the direct thread messages endpoint here.
    client = APIClient()
    client.force_authenticate(user=a)

    # send message from Alice to Bob
    url_post = reverse("v1:thread-messages", kwargs={"thread_id": t.id})
    r1 = client.post(url_post, {"body": "hey bob!"}, format="json")
    assert r1.status_code == 201, r1.data

    # Bob should see one new notification
    client_b = APIClient(); client_b.force_authenticate(user=b)
    url_list = reverse("v1:notifications-list")
    r2 = client_b.get(url_list)
    assert r2.status_code == 200, r2.data
    assert len(r2.data) == 1
    notif_id = r2.data[0]["id"]
    assert r2.data[0]["is_read"] is False
    assert r2.data[0]["title"] == "New message"

    # Mark single notification as read
    url_read_one = reverse("v1:notification-mark-read", kwargs={"pk": notif_id})
    r3 = client_b.post(url_read_one, {})
    assert r3.status_code == 200
    # verify
    r4 = client_b.get(url_list)
    assert r4.data[0]["is_read"] is True

    # Send another message to generate a second notification
    r5 = client.post(url_post, {"body": "another"}, format="json")
    assert r5.status_code == 201
    r6 = client_b.get(url_list)
    assert len(r6.data) == 2  # one read + one unread
    assert any(not n["is_read"] for n in r6.data)

    # Mark all read
    url_read_all = reverse("v1:notifications-mark-all-read")
    r7 = client_b.post(url_read_all, {})
    assert r7.status_code == 200

    r8 = client_b.get(url_list)
    assert all(n["is_read"] for n in r8.data)
