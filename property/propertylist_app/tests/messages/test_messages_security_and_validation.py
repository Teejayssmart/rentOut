import pytest
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import MessageThread, Message


pytestmark = pytest.mark.django_db


def _mk_users():
    u1 = User.objects.create_user(username="alice", email="a@x.com", password="pass12345")
    u2 = User.objects.create_user(username="bob", email="b@x.com", password="pass12345")
    u3 = User.objects.create_user(username="charlie", email="c@x.com", password="pass12345")
    return u1, u2, u3


def _mk_thread(u1, u2):
    t = MessageThread.objects.create()
    t.participants.set([u1, u2])
    return t


def test_thread_messages_requires_auth():
    u1, u2, _ = _mk_users()
    t = _mk_thread(u1, u2)

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    anon = APIClient()
    r = anon.get(url)

    # depending on permission setup, you may return 401 or 403
    assert r.status_code in (401, 403)


def test_user_cannot_read_another_users_thread():
    u1, u2, u3 = _mk_users()
    t = _mk_thread(u1, u2)

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    client = APIClient()
    client.force_authenticate(user=u3)

    r = client.get(url)

    # your API may choose 404 (hide existence) or 403 (explicit deny)
    assert r.status_code in (403, 404)


def test_user_cannot_post_to_thread_they_are_not_participant_of():
    u1, u2, u3 = _mk_users()
    t = _mk_thread(u1, u2)

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    client = APIClient()
    client.force_authenticate(user=u3)

    r = client.post(url, {"body": "hello"}, format="json")

    assert r.status_code in (403, 404)


def test_blank_message_rejected():
    u1, u2, _ = _mk_users()
    t = _mk_thread(u1, u2)

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    client = APIClient()
    client.force_authenticate(user=u1)

    r = client.post(url, {"body": ""}, format="json")
    assert r.status_code == 400


def test_cursor_pagination_no_duplicates_no_skips_across_pages():
    u1, u2, _ = _mk_users()
    t = _mk_thread(u1, u2)

    base = timezone.now() - timedelta(minutes=20)

    # create 12 messages with deterministic ordering
    created_ids = []
    for i in range(12):
        m = Message.objects.create(
            thread=t,
            sender=u1 if i % 2 == 0 else u2,
            body=f"m{i+1}",
            created=base + timedelta(minutes=i),
        )
        created_ids.append(m.id)

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    client = APIClient()
    client.force_authenticate(user=u1)

    seen_ids = []
    next_url = url

    # iterate pages until exhausted
    while next_url:
        resp = client.get(next_url)
        assert resp.status_code == 200
        assert "results" in resp.data

        page_ids = [item["id"] for item in resp.data["results"]]
        # no duplicates within page
        assert len(page_ids) == len(set(page_ids))

        seen_ids.extend(page_ids)
        next_url = resp.data.get("next")

    # no duplicates across pages
    assert len(seen_ids) == len(set(seen_ids))

    # and we saw all 12 messages
    assert set(seen_ids) == set(created_ids)


def test_cursor_consistency_when_new_message_arrives_between_page_fetches():
    u1, u2, _ = _mk_users()
    t = _mk_thread(u1, u2)

    base = timezone.now() - timedelta(minutes=20)

    # 7 messages total so we will have 2 pages if page size is 5 (as your existing test assumes)
    for i in range(7):
        Message.objects.create(
            thread=t,
            sender=u1 if i % 2 == 0 else u2,
            body=f"old-{i+1}",
            created=base + timedelta(minutes=i),
        )

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    client = APIClient()
    client.force_authenticate(user=u1)

    r1 = client.get(url)
    assert r1.status_code == 200
    page1_ids = [item["id"] for item in r1.data["results"]]
    next_url = r1.data.get("next")
    assert next_url

    # a new message arrives after page 1 was fetched
    new_msg = Message.objects.create(
        thread=t,
        sender=u2,
        body="new-between-pages",
        created=timezone.now(),
    )

    r2 = client.get(next_url)
    assert r2.status_code == 200
    page2_ids = [item["id"] for item in r2.data["results"]]

    # expectation: page 2 should NOT include the newly-created message,
    # and should not duplicate items from page 1
    assert new_msg.id not in page2_ids
    assert set(page1_ids).isdisjoint(set(page2_ids))
