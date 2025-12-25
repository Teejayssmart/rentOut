import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import Notification

pytestmark = pytest.mark.django_db

# change this ONLY if your API prefix is not /api
API_PREFIX = "/api"


def url_notifications_list():
    return f"{API_PREFIX}/notifications/"


def url_notification_mark_read(pk: int):
    return f"{API_PREFIX}/notifications/{pk}/read/"


def url_notifications_mark_all_read():
    return f"{API_PREFIX}/notifications/read/all/"


def _auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _mk_user(username="u1"):
    User = get_user_model()
    return User.objects.create_user(username=username, password="pass12345")


def _mk_notification(user, *, ntype="message", title="T", body="B", is_read=False):
    return Notification.objects.create(
        user=user,
        type=ntype,
        title=title,
        body=body,
        is_read=is_read,
    )


def test_notifications_list_requires_auth():
    client = APIClient()
    res = client.get(url_notifications_list())
    assert res.status_code in (401, 403)


def test_notifications_list_returns_only_my_notifications():
    u1 = _mk_user("u1")
    u2 = _mk_user("u2")

    _mk_notification(u1, title="mine-1")
    _mk_notification(u1, title="mine-2")
    _mk_notification(u2, title="theirs-1")

    client = _auth_client(u1)
    res = client.get(url_notifications_list())
    assert res.status_code == 200

    data = res.data if isinstance(res.data, list) else res.data["results"]# works for paginated + non-paginated
    titles = [n.get("title") for n in data]

    assert "mine-1" in titles
    assert "mine-2" in titles
    assert "theirs-1" not in titles


def test_notification_mark_read_marks_single_notification():
    u1 = _mk_user("u1")
    n = _mk_notification(u1, is_read=False)

    client = _auth_client(u1)
    res = client.post(url_notification_mark_read(n.id))
    assert res.status_code in (200, 204)

    n.refresh_from_db()
    assert n.is_read is True


def test_notification_mark_read_cannot_mark_other_users_notification():
    u1 = _mk_user("u1")
    u2 = _mk_user("u2")

    n2 = _mk_notification(u2, is_read=False)

    client = _auth_client(u1)
    res = client.post(url_notification_mark_read(n2.id))
    assert res.status_code in (404, 403)

    n2.refresh_from_db()
    assert n2.is_read is False


def test_notifications_mark_all_read_marks_only_my_unread():
    u1 = _mk_user("u1")
    u2 = _mk_user("u2")

    n1 = _mk_notification(u1, title="u1-a", is_read=False)
    n2 = _mk_notification(u1, title="u1-b", is_read=False)
    n3 = _mk_notification(u1, title="u1-read", is_read=True)
    n4 = _mk_notification(u2, title="u2-a", is_read=False)

    client = _auth_client(u1)
    res = client.post(url_notifications_mark_all_read())
    assert res.status_code in (200, 204)

    n1.refresh_from_db()
    n2.refresh_from_db()
    n3.refresh_from_db()
    n4.refresh_from_db()

    assert n1.is_read is True
    assert n2.is_read is True
    assert n3.is_read is True
    assert n4.is_read is False
