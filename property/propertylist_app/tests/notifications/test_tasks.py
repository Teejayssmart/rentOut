import pytest
from unittest.mock import patch
from datetime import date, timedelta
from django.contrib.auth import get_user_model

from propertylist_app.models import Room, RoomCategorie
from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.notifications.tasks import notify_listing_expiring, send_due_notifications

pytestmark = pytest.mark.django_db


def setup_room_with_owner(expiring_in_days=3):
    U = get_user_model()
    owner = U.objects.create_user(
        username="own",
        email="own@ex.com",
        password="x",
        first_name="Owner",
    )
    cat = RoomCategorie.objects.create(name="General", key="general", slug="general", active=True)
    r = Room.objects.create(
        title="R1",
        description="d",
        price_per_month=500,
        location="SO14",
        category=cat,
        property_owner=owner,
        property_type="flat",
        paid_until=date.today() + timedelta(days=expiring_in_days),
    )
    return r, owner


def test_notify_listing_expiring_queues_owner_email_and_send_due_delivers():
    room, owner = setup_room_with_owner(3)

    NotificationTemplate.objects.create(
        key="listing.expiring",
        channel="email",
        subject="Expires",
        body="Hi {{ user.first_name }}",
        is_active=True,
    )

    # queue expiry emails
    notify_listing_expiring()

    out_qs = OutboundNotification.objects.filter(template_key="listing.expiring", user=owner)
    assert out_qs.count() == 1

    out = out_qs.first()
    assert out is not None

    # deliver them (mock email sending)
    with patch("notifications.services.send_mail", return_value=1):
        send_due_notifications()

    out.refresh_from_db()
    assert out.status == OutboundNotification.STATUS_SENT
