# property/propertylist_app/tests/reviews/test_user_profile_ratings_after_reveal.py

from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from propertylist_app.tasks import task_tenancy_prompts_sweep


pytestmark = pytest.mark.django_db


def _get_model(app_label, model_name):
    return apps.get_model(app_label, model_name)


def _make_booking(user, room, *, days_ago: int = 2):
    """
    Booking == viewing proof (eligibility), not a review trigger.
    Create a completed viewing by setting booking end in the past.
    """
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


def _make_tenancy(room, landlord, tenant, *, proposed_by, status):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    now = timezone.now()

    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=proposed_by,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=3,
        status=status,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
    )


def test_tenant_profile_rating_updates_only_after_reveal(user_factory, room_factory):
    """
    Landlord -> Tenant review should update tenant's UserProfile tenant rating
    ONLY after reveal (active=True and reveal_at <= now).
    """
    Review = _get_model("propertylist_app", "Review")
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="rt_landlord_rates_tenant")
    tenant = user_factory(username="rt_tenant_gets_rated")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ENDED,
    )

    # Fail fast if fields are not added yet (so you know what to implement)
    tenant_profile = tenant.profile
    assert hasattr(tenant_profile, "avg_tenant_rating"), "Add avg_tenant_rating to UserProfile"
    assert hasattr(tenant_profile, "number_tenant_ratings"), "Add number_tenant_ratings to UserProfile"

    # Create a hidden review (not revealed yet)
    future = timezone.now() + timedelta(days=7)

    # Review.save() computes overall_rating from review_flags:
    # overall_rating = 3 + (pos - neg). Two positives => 5.
    flags_for_5 = ["responsive", "maintenance_good"]

    Review.objects.create(
        tenancy=tenancy,
        reviewer=landlord,
        reviewee=tenant,
        role=Review.ROLE_LANDLORD_TO_TENANT,
        review_flags=flags_for_5,
        notes="Landlord rates tenant",
        reveal_at=future,
        active=False,
    )

    # BEFORE reveal -> tenant rating must not change
    tenant.profile.refresh_from_db()
    before_avg = float(getattr(tenant.profile, "avg_tenant_rating", 0.0) or 0.0)
    before_cnt = int(getattr(tenant.profile, "number_tenant_ratings", 0) or 0)

    task_tenancy_prompts_sweep()

    tenant.profile.refresh_from_db()
    mid_avg = float(getattr(tenant.profile, "avg_tenant_rating", 0.0) or 0.0)
    mid_cnt = int(getattr(tenant.profile, "number_tenant_ratings", 0) or 0)

    assert mid_avg == before_avg
    assert mid_cnt == before_cnt

    # Force reveal and sweep again
    past = timezone.now() - timedelta(days=1)
    Review.objects.filter(tenancy=tenancy, role=Review.ROLE_LANDLORD_TO_TENANT).update(reveal_at=past)

    task_tenancy_prompts_sweep()

    tenant.profile.refresh_from_db()
    after_avg = float(getattr(tenant.profile, "avg_tenant_rating", 0.0) or 0.0)
    after_cnt = int(getattr(tenant.profile, "number_tenant_ratings", 0) or 0)

    assert abs(after_avg - 5.0) < 0.0001
    assert after_cnt == 1


def test_landlord_profile_rating_updates_only_after_reveal(user_factory, room_factory):
    """
    Tenant -> Landlord review should update landlord's UserProfile landlord rating
    ONLY after reveal (active=True and reveal_at <= now).
    """
    Review = _get_model("propertylist_app", "Review")
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="rl_landlord_gets_rated")
    tenant = user_factory(username="rl_tenant_rates_landlord")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ENDED,
    )

    landlord_profile = landlord.profile
    assert hasattr(landlord_profile, "avg_landlord_rating"), "Add avg_landlord_rating to UserProfile"
    assert hasattr(landlord_profile, "number_landlord_ratings"), "Add number_landlord_ratings to UserProfile"

    future = timezone.now() + timedelta(days=7)
    flags_for_5 = ["responsive", "maintenance_good"]

    Review.objects.create(
        tenancy=tenancy,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=flags_for_5,
        notes="Tenant rates landlord",
        reveal_at=future,
        active=False,
    )

    # BEFORE reveal -> landlord rating must not change
    landlord.profile.refresh_from_db()
    before_avg = float(getattr(landlord.profile, "avg_landlord_rating", 0.0) or 0.0)
    before_cnt = int(getattr(landlord.profile, "number_landlord_ratings", 0) or 0)

    task_tenancy_prompts_sweep()

    landlord.profile.refresh_from_db()
    mid_avg = float(getattr(landlord.profile, "avg_landlord_rating", 0.0) or 0.0)
    mid_cnt = int(getattr(landlord.profile, "number_landlord_ratings", 0) or 0)

    assert mid_avg == before_avg
    assert mid_cnt == before_cnt

    # Force reveal and sweep again
    past = timezone.now() - timedelta(days=1)
    Review.objects.filter(tenancy=tenancy, role=Review.ROLE_TENANT_TO_LANDLORD).update(reveal_at=past)

    task_tenancy_prompts_sweep()

    landlord.profile.refresh_from_db()
    after_avg = float(getattr(landlord.profile, "avg_landlord_rating", 0.0) or 0.0)
    after_cnt = int(getattr(landlord.profile, "number_landlord_ratings", 0) or 0)

    assert abs(after_avg - 5.0) < 0.0001
    assert after_cnt == 1
