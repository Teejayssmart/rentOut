import pytest
from datetime import timedelta
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from propertylist_app.models import MessageThread, Message


@pytest.mark.django_db
def test_messages_default_ordering_desc_and_limit_offset_next():
    # users
    u1 = User.objects.create_user(username="alice", email="a@x.com", password="pass12345")
    u2 = User.objects.create_user(username="bob", email="b@x.com", password="pass12345")

    # auth
    client = APIClient()
    client.force_authenticate(user=u1)

    # thread with both participants
    thread = MessageThread.objects.create()
    thread.participants.set([u1, u2])

    # create 6 messages spaced 1 minute apart (older -> newer)
    base = timezone.now() - timedelta(minutes=6)
    for i in range(6):
        Message.objects.create(
            thread=thread,
            sender=u1 if i % 2 == 0 else u2,
            body=f"Message {i+1}",
            created=base + timedelta(minutes=i),
        )

    url = reverse("v1:thread-messages", kwargs={"thread_id": thread.pk})

    # 1) First page with explicit limit=5: should return 5 newest messages, newest first
    r1 = client.get(url, {"limit": 5})
    assert r1.status_code == 200

    body1 = r1.json()
    assert body1.get("ok") is True
    assert isinstance(body1.get("data"), list)
    assert isinstance(body1.get("meta"), dict)

    items1 = body1["data"]
    meta1 = body1["meta"]

    assert len(items1) == 5
    bodies_page1 = [item["body"] for item in items1]
    assert bodies_page1 == ["Message 6", "Message 5", "Message 4", "Message 3", "Message 2"]

    next_url = meta1.get("next")
    assert next_url, "Expected a next link for the remaining messages"

    # 2) Follow next page: should return the remaining oldest message
    r2 = client.get(next_url)
    assert r2.status_code == 200

    body2 = r2.json()
    assert body2.get("ok") is True
    assert isinstance(body2.get("data"), list)
    assert isinstance(body2.get("meta"), dict)

    items2 = body2["data"]
    meta2 = body2["meta"]

    bodies_page2 = [item["body"] for item in items2]
    assert bodies_page2 == ["Message 1"]

    # and no further pages
    assert not meta2.get("next")