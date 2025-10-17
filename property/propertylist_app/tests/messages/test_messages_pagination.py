import pytest
from datetime import timedelta
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from propertylist_app.models import MessageThread, Message

@pytest.mark.django_db
def test_messages_default_ordering_desc_and_cursor_next():
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
    msgs = []
    for i in range(6):
        m = Message.objects.create(
            thread=thread,
            sender=u1 if i % 2 == 0 else u2,
            body=f"Message {i+1}",
            created=base + timedelta(minutes=i),
        )
        msgs.append(m)

    url = reverse("v1:thread-messages", kwargs={"thread_id": thread.pk})

    # 1) First page (no cursor): should return 5 newest messages, newest first
    r1 = client.get(url)
    assert r1.status_code == 200

    # expect pagination structure with 'results' and 'next'
    assert "results" in r1.data
    assert len(r1.data["results"]) == 5
    assert "next" in r1.data

    # newest is Message 6; oldest on this page is Message 2
    bodies_page1 = [item["body"] for item in r1.data["results"]]
    assert bodies_page1 == ["Message 6", "Message 5", "Message 4", "Message 3", "Message 2"]

    # 2) Follow the 'next' cursor to get older items (should return the remaining oldest message)
    next_url = r1.data["next"]
    assert next_url, "Expected a next cursor link for the remaining messages"

    r2 = client.get(next_url)
    assert r2.status_code == 200
    assert "results" in r2.data

    bodies_page2 = [item["body"] for item in r2.data["results"]]
    assert bodies_page2 == ["Message 1"]  # only the oldest remains

    # and no further pages
    assert not r2.data.get("next")
