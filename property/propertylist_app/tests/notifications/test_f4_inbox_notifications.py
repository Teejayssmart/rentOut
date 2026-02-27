import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Notification


@pytest.mark.django_db
def test_f4_inbox_includes_only_my_notifications(user_factory):
    """
    F4 backend readiness:
    - /api/v1/inbox/ returns notifications + threads merged
    - notifications are scoped to request.user only
    """
    client = APIClient()

    user_a = user_factory(username="user_a", email="a@example.com")
    user_b = user_factory(username="user_b", email="b@example.com")

    # Create notifications for both users
    n_a1 = Notification.objects.create(
        user=user_a,
        type="confirmation",
        title="A1",
        body="Hello A",
        is_read=False,
    )
    Notification.objects.create(
        user=user_b,
        type="confirmation",
        title="B1",
        body="Hello B",
        is_read=False,
    )

    client.force_authenticate(user=user_a)

    url = reverse("api:inbox-list")
    resp = client.get(url)

    assert resp.status_code == 200
    assert resp.data.get("ok") is True

    items = resp.data.get("data") or []
    assert isinstance(items, list)

    # Only user_a's notification should appear
    notif_ids = [i.get("notification_id") for i in items if i.get("kind") == "notification"]
    assert n_a1.id in notif_ids
    assert all(nid != 0 for nid in notif_ids if nid is not None)

    # Ensure no leakage from user_b
    assert Notification.objects.filter(user=user_b).first().id not in notif_ids
    
    
    

@pytest.mark.django_db
def test_f4_notification_mark_read_is_user_scoped(user_factory):
    client = APIClient()

    user_a = user_factory(username="user_a2", email="a2@example.com")
    user_b = user_factory(username="user_b2", email="b2@example.com")

    n_b = Notification.objects.create(
        user=user_b,
        type="confirmation",
        title="B only",
        body="Private",
        is_read=False,
    )

    client.force_authenticate(user=user_a)

    url = reverse("api:notification-mark-read", kwargs={"pk": n_b.id})
    resp = client.post(url)

    # get_object_or_404(Notification, pk=pk, user=request.user) => 404 for other users
    assert resp.status_code == 404

    n_b.refresh_from_db()
    assert n_b.is_read is False
    
    


@pytest.mark.django_db
def test_f4_notifications_list_orders_unread_first(user_factory):
    client = APIClient()
    user = user_factory(username="u_notifs", email="u_notifs@example.com")
    client.force_authenticate(user=user)

    # Create read + unread
    n_read = Notification.objects.create(
        user=user, type="confirmation", title="Read", body="r", is_read=True
    )
    n_unread = Notification.objects.create(
        user=user, type="confirmation", title="Unread", body="u", is_read=False
    )

    url = reverse("api:notifications-list")
    resp = client.get(url)

    assert resp.status_code == 200
    data = resp.data
    assert isinstance(data, list)
    assert len(data) >= 2

    # First item should be unread (is_read False comes first)
    assert data[0]["is_read"] is False
    ids = [row["id"] for row in data]
    assert n_unread.id in ids and n_read.id in ids    
    
    
    
    
    