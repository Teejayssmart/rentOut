# propertylist_app/tests/notifications/test_tenancy_and_review_notifications.py

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


def test_tenancy_proposal_creates_inbox_notification(user_factory, room_factory):
    Notification = __import__("django.apps").apps.apps.get_model("propertylist_app", "Notification")
    Tenancy = __import__("django.apps").apps.apps.get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="n_landlord_proposed")
    tenant = user_factory(username="n_tenant_proposed")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)  # completed viewing

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,  # landlord proposed => target user is tenant (per your task logic)
        move_in_date=date.today() + timedelta(days=7),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,
    )

    before = Notification.objects.count()
    created = task_send_tenancy_notification(tenancy.id, "proposed")
    after = Notification.objects.count()

    assert created == 1
    assert after == before + 1

    n = Notification.objects.latest("id")
    assert n.user_id == tenant.id
    assert n.type == "tenancy_proposed"


def test_tenancy_confirmation_creates_notifications_for_both_users(user_factory, room_factory):
    Notification = __import__("django.apps").apps.apps.get_model("propertylist_app", "Notification")
    Tenancy = __import__("django.apps").apps.apps.get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="n_landlord_confirmed")
    tenant = user_factory(username="n_tenant_confirmed")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_CONFIRMED,
    )

    before = Notification.objects.count()
    created = task_send_tenancy_notification(tenancy.id, "confirmed")
    after = Notification.objects.count()

    assert created == 2
    assert after == before + 2

    qs = Notification.objects.filter(type="tenancy_confirmed").order_by("-id")[:2]
    user_ids = {n.user_id for n in qs}
    assert user_ids == {landlord.id, tenant.id}


def test_review_open_at_triggers_review_available_notification(user_factory, room_factory):
    Notification = __import__("django.apps").apps.apps.get_model("propertylist_app", "Notification")
    Tenancy = __import__("django.apps").apps.apps.get_model("propertylist_app", "Tenancy")
    Review = __import__("django.apps").apps.apps.get_model("propertylist_app", "Review")

    landlord = user_factory(username="n_landlord_review_open")
    tenant = user_factory(username="n_tenant_review_open")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ENDED,
    )
    tenancy.review_open_at = timezone.now() - timedelta(days=1)
    tenancy.review_deadline_at = timezone.now() + timedelta(days=30)
    tenancy.save(update_fields=["review_open_at", "review_deadline_at"])

    # Ensure at least one review is missing (the task should notify)
    Review.objects.filter(tenancy=tenancy).delete()

    before = Notification.objects.filter(type="review_available").count()
    task_tenancy_prompts_sweep()
    after = Notification.objects.filter(type="review_available").count()

    # should notify both sides
    assert after == before + 2
    qs = Notification.objects.filter(type="review_available").order_by("-id")[:2]
    user_ids = {n.user_id for n in qs}
    assert user_ids == {landlord.id, tenant.id}


def test_still_living_check_triggers_notification_for_both_users(user_factory, room_factory):
    Notification = __import__("django.apps").apps.apps.get_model("propertylist_app", "Notification")
    Tenancy = __import__("django.apps").apps.apps.get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="n_landlord_still_living")
    tenant = user_factory(username="n_tenant_still_living")
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
    qs = Notification.objects.filter(type="tenancy_still_living_check").order_by("-id")[:2]
    user_ids = {n.user_id for n in qs}
    assert user_ids == {landlord.id, tenant.id}
