# propertylist_app/tests/tenancies/test_tenancy_notifications.py

from datetime import date, timedelta

import pytest
from django.utils import timezone

from propertylist_app.tasks import (
    task_send_tenancy_notification,
    task_tenancy_prompts_sweep,
)

pytestmark = pytest.mark.django_db


def _make_booking(user, room, *, days_ago: int = 2):
    """
    Completed viewing = booking end is in the past.
    Matches your rule: must be viewed (not just booked).
    """
    Booking = __import__("django.apps").apps.apps.get_model("propertylist_app", "Booking")

    end = timezone.now() - timedelta(days=days_ago)
    start = end - timedelta(minutes=30)

    return Booking.objects.create(
        user=user,
        room=room,
        start=start,
        end=end,
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )


def _make_tenancy(
    room,
    landlord,
    tenant,
    *,
    proposed_by,
    status,
    move_in_days_ago=90,
    duration_months=3,
):
    Tenancy = __import__("django.apps").apps.apps.get_model("propertylist_app", "Tenancy")

    now = timezone.now()
    move_in = date.today() - timedelta(days=move_in_days_ago)

    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=proposed_by,
        move_in_date=move_in,
        duration_months=duration_months,
        status=status,
        landlord_confirmed_at=now - timedelta(days=move_in_days_ago),
        tenant_confirmed_at=now - timedelta(days=move_in_days_ago),
    )


def test_tenancy_proposal_creates_notification(user_factory, room_factory):
    Notification = __import__("django.apps").apps.apps.get_model("propertylist_app", "Notification")
    Tenancy = __import__("django.apps").apps.apps.get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="nt_landlord_proposed")
    tenant = user_factory(username="nt_tenant_proposed")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,  # landlord proposed => notify tenant
        move_in_date=date.today() + timedelta(days=7),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,
    )

    before = Notification.objects.filter(type="tenancy_proposed").count()
    created = task_send_tenancy_notification(tenancy.id, "proposed")
    after = Notification.objects.filter(type="tenancy_proposed").count()

    assert created == 1
    assert after == before + 1

    n = Notification.objects.filter(type="tenancy_proposed").latest("id")
    assert n.user_id == tenant.id


def test_tenancy_confirmation_creates_notifications_for_both_users(user_factory, room_factory):
    Notification = __import__("django.apps").apps.apps.get_model("propertylist_app", "Notification")
    Tenancy = __import__("django.apps").apps.apps.get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="nt_landlord_confirmed")
    tenant = user_factory(username="nt_tenant_confirmed")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_CONFIRMED,
    )

    before = Notification.objects.filter(type="tenancy_confirmed").count()
    created = task_send_tenancy_notification(tenancy.id, "confirmed")
    after = Notification.objects.filter(type="tenancy_confirmed").count()

    assert created == 2
    assert after == before + 2

    qs = Notification.objects.filter(type="tenancy_confirmed").order_by("-id")[:2]
    user_ids = {n.user_id for n in qs}
    assert user_ids == {landlord.id, tenant.id}





def test_tenancy_confirmation_pushes_realtime_envelope_events_for_landlord(
    user_factory,
    room_factory,
    monkeypatch,
):
    Tenancy = __import__("django.apps").apps.apps.get_model(
        "propertylist_app",
        "Tenancy",
    )

    landlord = user_factory(username="nt_landlord_confirmed_realtime")
    tenant = user_factory(username="nt_tenant_confirmed_realtime")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
        status=Tenancy.STATUS_CONFIRMED,
    )

    pushed_events = []

    def fake_push_user_realtime_event(user_id, event_type, data):
        pushed_events.append(
            {
                "user_id": user_id,
                "event_type": event_type,
                "data": data,
            }
        )

    monkeypatch.setattr(
        "propertylist_app.tasks.push_user_realtime_event",
        fake_push_user_realtime_event,
    )

    created = task_send_tenancy_notification(
        tenancy.id,
        "confirmed",
    )

    assert created == 2

    landlord_events = [
        event
        for event in pushed_events
        if event["user_id"] == landlord.id
    ]

    event_types = {
        event["event_type"]
        for event in landlord_events
    }

    assert "new_notification" in event_types
    assert "new_message" in event_types
    assert "unread_count_changed" in event_types

    new_message_event = next(
        event
        for event in landlord_events
        if event["event_type"] == "new_message"
    )

    assert new_message_event["data"]["thread_id"] is not None
    assert new_message_event["data"]["message_id"] is not None

    unread_event = next(
        event
        for event in landlord_events
        if event["event_type"] == "unread_count_changed"
    )

    assert unread_event["data"]["thread_unread_count"] >= 1
    assert unread_event["data"]["account_unread_total"] >= 1











def test_still_living_check_at_triggers_notification_for_both_users(user_factory, room_factory):
    Notification = __import__("django.apps").apps.apps.get_model("propertylist_app", "Notification")
    Tenancy = __import__("django.apps").apps.apps.get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="nt_landlord_still_living")
    tenant = user_factory(username="nt_tenant_still_living")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
    )
    tenancy.still_living_check_at = timezone.now() - timedelta(days=1)
    tenancy.still_living_confirmed_at = None
    tenancy.save(update_fields=["still_living_check_at", "still_living_confirmed_at"])

    before = Notification.objects.filter(type="tenancy_still_living_check").count()
    task_tenancy_prompts_sweep()
    after = Notification.objects.filter(type="tenancy_still_living_check").count()

    assert after == before + 2

    qs = Notification.objects.filter(
    type="tenancy_still_living_check",
    user_id__in=[landlord.id, tenant.id],
    ).order_by("-id")[:2]

    notifications = {n.user_id: n for n in qs}

    assert set(notifications) == {landlord.id, tenant.id}

    assert notifications[landlord.id].target_type == "still_living_check"
    assert notifications[landlord.id].target_id == tenancy.id

    assert notifications[tenant.id].target_type == "still_living_check"
    assert notifications[tenant.id].target_id == tenancy.id
    
    
def test_still_living_check_does_not_duplicate_legacy_landlord_booking_target(
    user_factory,
    room_factory,
):
    Notification = __import__("django.apps").apps.apps.get_model(
        "propertylist_app",
        "Notification",
    )
    Tenancy = __import__("django.apps").apps.apps.get_model(
        "propertylist_app",
        "Tenancy",
    )

    landlord = user_factory(username="nt_landlord_legacy_dedupe")
    tenant = user_factory(username="nt_tenant_legacy_dedupe")
    room = room_factory(property_owner=landlord)

    booking = _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
    )

    tenancy.still_living_check_at = timezone.now() - timedelta(days=1)
    tenancy.still_living_confirmed_at = None
    tenancy.save(
        update_fields=[
            "still_living_check_at",
            "still_living_confirmed_at",
        ]
    )

    Notification.objects.create(
        user=landlord,
        type="tenancy_still_living_check",
        target_type="booking",
        target_id=booking.id,
        title="Your tenancy is ending soon",
        body="Legacy landlord reminder",
    )

    landlord_before = Notification.objects.filter(
        user=landlord,
        type="tenancy_still_living_check",
    ).count()

    task_tenancy_prompts_sweep()

    landlord_after = Notification.objects.filter(
        user=landlord,
        type="tenancy_still_living_check",
    ).count()

    assert landlord_after == landlord_before    
