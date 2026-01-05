# property/propertylist_app/tests/reviews/test_review_reveal_transition_task.py

from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from propertylist_app.tasks import task_tenancy_prompts_sweep


pytestmark = pytest.mark.django_db


def _get_model(app_label, model_name):
    return apps.get_model(app_label, model_name)


def _make_booking(user, room, *, days_ago: int = 2):
    Booking = _get_model("propertylist_app", "Booking")

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


def _make_tenancy(room, landlord, tenant, *, status):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    now = timezone.now()

    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=3,
        status=status,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
    )


def _create_review(*, tenancy, reviewer, reviewee, role, rating=5, reveal_at=None, active=False):
    Review = _get_model("propertylist_app", "Review")

    return Review.objects.create(
        tenancy=tenancy,
        reviewer=reviewer,
        reviewee=reviewee,
        role=role,
        overall_rating=rating,
        notes="ok",
        reveal_at=reveal_at,
        active=active,
        submitted_at=timezone.now(),
    )


def test_one_side_submits_deadline_not_passed_nothing_reveals(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rt_landlord1")
    tenant = user_factory(username="rt_tenant1")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    # review window open, deadline in future
    tenancy.review_open_at = timezone.now() - timedelta(days=1)
    tenancy.review_deadline_at = timezone.now() + timedelta(days=7)
    tenancy.save(update_fields=["review_open_at", "review_deadline_at"])

    future_reveal = timezone.now() + timedelta(days=7)

    # Only tenant submits
    r1 = _create_review(
        tenancy=tenancy,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        rating=5,
        reveal_at=future_reveal,
        active=False,
    )

    task_tenancy_prompts_sweep()

    r1.refresh_from_db()
    assert r1.active is False


def test_both_sides_submit_then_reveal_happens(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rt_landlord2")
    tenant = user_factory(username="rt_tenant2")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    tenancy.review_open_at = timezone.now() - timedelta(days=1)
    tenancy.review_deadline_at = timezone.now() + timedelta(days=7)
    tenancy.save(update_fields=["review_open_at", "review_deadline_at"])

    # Both reviews have reveal_at in the past to allow sweep to flip active
    past_reveal = timezone.now() - timedelta(days=1)

    r_tenant = _create_review(
        tenancy=tenancy,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        rating=5,
        reveal_at=past_reveal,
        active=False,
    )
    r_landlord = _create_review(
        tenancy=tenancy,
        reviewer=landlord,
        reviewee=tenant,
        role=Review.ROLE_LANDLORD_TO_TENANT,
        rating=5,
        reveal_at=past_reveal,
        active=False,
    )

    task_tenancy_prompts_sweep()

    r_tenant.refresh_from_db()
    r_landlord.refresh_from_db()
    assert r_tenant.active is True
    assert r_landlord.active is True


def test_deadline_passed_even_if_one_missing_review_reveals_existing(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rt_landlord3")
    tenant = user_factory(username="rt_tenant3")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    # deadline already passed
    tenancy.review_open_at = timezone.now() - timedelta(days=10)
    tenancy.review_deadline_at = timezone.now() - timedelta(days=1)
    tenancy.save(update_fields=["review_open_at", "review_deadline_at"])

    past_reveal = timezone.now() - timedelta(days=1)

    r1 = _create_review(
        tenancy=tenancy,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        rating=5,
        reveal_at=past_reveal,
        active=False,
    )

    task_tenancy_prompts_sweep()

    r1.refresh_from_db()
    assert r1.active is True
