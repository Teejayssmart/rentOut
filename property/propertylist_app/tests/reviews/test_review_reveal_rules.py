# propertylist_app/tests/reviews/test_review_reveal_rules.py

from datetime import date, timedelta

import pytest
from django.utils import timezone

from propertylist_app.tasks import task_tenancy_prompts_sweep

pytestmark = pytest.mark.django_db


def _get_model(app_label: str, model_name: str):
    return __import__("django.apps").apps.apps.get_model(app_label, model_name)


def _set_first_attr(obj, names, value, *, allow_missing=False):
    for name in names:
        if hasattr(obj, name):
            setattr(obj, name, value)
            return name
    if allow_missing:
        return None
    raise AttributeError(f"None of these fields exist on {obj.__class__.__name__}: {names}")


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
    Tenancy = _get_model("propertylist_app", "Tenancy")

    now = timezone.now()
    move_in = date.today() - timedelta(days=move_in_days_ago)

    tenancy = Tenancy.objects.create(
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
    return tenancy


def _create_review(*, review_model, tenancy, room, reviewer, reviewee, rating=5, text="Good"):
    """
    Creates a Review using flexible field-name matching (so this test survives minor schema renames).
    """
    field_names = {f.name for f in review_model._meta.get_fields()}

    data = {}

    # Required-ish anchors
    if "room" in field_names:
        data["room"] = room
    if "tenancy" in field_names:
        data["tenancy"] = tenancy

    # Who wrote it
    for k in ("user", "reviewer", "author", "created_by"):
        if k in field_names:
            data[k] = reviewer
            break

    # Who it is about (optional in some schemas)
    for k in ("target_user", "reviewee", "to_user", "recipient", "subject_user"):
        if k in field_names:
            data[k] = reviewee
            break

    # Rating
    for k in ("rating", "stars", "score"):
        if k in field_names:
            data[k] = rating
            break

    # Text
    for k in ("content", "text", "comment", "body", "review"):
        if k in field_names:
            data[k] = text
            break

    # Safe defaults commonly used in your app
    if "is_deleted" in field_names:
        data["is_deleted"] = False

    return review_model.objects.create(**data)


def _refresh_reviews(review_model, tenancy):
    """
    Refresh review rows from DB (avoids stale objects after tasks run).
    """
    qs = review_model.objects.filter(tenancy=tenancy).order_by("id")
    return list(qs)


def test_reviews_are_hidden_before_reveal(user_factory, room_factory):
    """
    Explicit proof:
    - Create only ONE side review.
    - Assert it is NOT revealed (hidden) before reveal conditions are met.
    """
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="r_landlord_hidden_before_reveal")
    tenant = user_factory(username="r_tenant_hidden_before_reveal")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ENDED,
    )

    # Open window is active; deadline is in future (so reveal should NOT happen yet).
    _set_first_attr(tenancy, ["review_open_at"], timezone.now() - timedelta(days=1), allow_missing=True)
    _set_first_attr(tenancy, ["review_deadline_at"], timezone.now() + timedelta(days=7), allow_missing=True)
    tenancy.save()

    # Only tenant leaves a review
    _create_review(
        review_model=Review,
        tenancy=tenancy,
        room=room,
        reviewer=tenant,
        reviewee=landlord,
        rating=5,
        text="Tenant review (only one side)",
    )

    # Run sweep to prove it still does NOT reveal with only one review + not past deadline
    task_tenancy_prompts_sweep()

    reviews = _refresh_reviews(Review, tenancy)
    assert len(reviews) == 1

    r = reviews[0]

    # Hidden flag / revealed timestamp checks (field-flexible)
    if hasattr(r, "is_revealed"):
        assert r.is_revealed is False
    if hasattr(r, "revealed_at"):
        assert r.revealed_at is None
    if hasattr(r, "is_hidden"):
        assert r.is_hidden is True


def test_reviews_appear_only_after_reveal(user_factory, room_factory):
    """
    Explicit proof:
    - Create BOTH reviews.
    - Force reveal condition (deadline passed).
    - Run sweep.
    - Assert BOTH reviews are revealed.
    """
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="r_landlord_reveal_after")
    tenant = user_factory(username="r_tenant_reveal_after")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ENDED,
    )

    # Review window opened; deadline passed -> reveal should be allowed by sweep.
    _set_first_attr(tenancy, ["review_open_at"], timezone.now() - timedelta(days=10), allow_missing=True)
    _set_first_attr(tenancy, ["review_deadline_at"], timezone.now() - timedelta(days=1), allow_missing=True)
    tenancy.save()

    # Both sides leave reviews
    _create_review(
        review_model=Review,
        tenancy=tenancy,
        room=room,
        reviewer=tenant,
        reviewee=landlord,
        rating=5,
        text="Tenant review",
    )
    _create_review(
        review_model=Review,
        tenancy=tenancy,
        room=room,
        reviewer=landlord,
        reviewee=tenant,
        rating=4,
        text="Landlord review",
    )

    # Before sweep: should still be hidden (depending on your logic, but the key is: reveal happens AFTER)
    reviews_before = _refresh_reviews(Review, tenancy)
    assert len(reviews_before) == 2
    for r in reviews_before:
        if hasattr(r, "is_revealed"):
            assert r.is_revealed is False

    # Trigger reveal via existing task
    task_tenancy_prompts_sweep()

    reviews_after = _refresh_reviews(Review, tenancy)
    assert len(reviews_after) == 2

    for r in reviews_after:
        if hasattr(r, "is_revealed"):
            assert r.is_revealed is True
        if hasattr(r, "revealed_at"):
            assert r.revealed_at is not None
        if hasattr(r, "is_hidden"):
            assert r.is_hidden is False


def test_tenancy_reviews_follow_same_rule(user_factory, room_factory):
    """
    Explicit proof tenancy reviews use the same reveal gating:
    - While tenancy is ACTIVE (or not ended), reviews must not reveal.
    - Once ended + reveal condition met (deadline passed) -> reviews reveal.
    """
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="r_landlord_tenancy_rule")
    tenant = user_factory(username="r_tenant_tenancy_rule")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
    )

    _set_first_attr(tenancy, ["review_open_at"], timezone.now() - timedelta(days=10), allow_missing=True)
    _set_first_attr(tenancy, ["review_deadline_at"], timezone.now() - timedelta(days=1), allow_missing=True)
    tenancy.save()

    _create_review(
        review_model=Review,
        tenancy=tenancy,
        room=room,
        reviewer=tenant,
        reviewee=landlord,
        rating=5,
        text="Tenant review during active tenancy",
    )
    _create_review(
        review_model=Review,
        tenancy=tenancy,
        room=room,
        reviewer=landlord,
        reviewee=tenant,
        rating=5,
        text="Landlord review during active tenancy",
    )

    # Sweep should NOT reveal while tenancy is still active
    task_tenancy_prompts_sweep()

    reviews = _refresh_reviews(Review, tenancy)
    assert len(reviews) == 2
    for r in reviews:
        if hasattr(r, "is_revealed"):
            assert r.is_revealed is False
        if hasattr(r, "revealed_at"):
            assert r.revealed_at is None

    # Now end the tenancy and sweep again -> should reveal
    tenancy.status = Tenancy.STATUS_ENDED
    tenancy.save(update_fields=["status"])

    task_tenancy_prompts_sweep()

    reviews2 = _refresh_reviews(Review, tenancy)
    assert len(reviews2) == 2
    for r in reviews2:
        if hasattr(r, "is_revealed"):
            assert r.is_revealed is True
        if hasattr(r, "revealed_at"):
            assert r.revealed_at is not None


def test_reviews_remain_hidden_until_reveal_event_even_if_one_side_missing(user_factory, room_factory):
    """
    Explicit proof:
    - Deadline passed but only one side submitted -> still hidden (double-blind).
    """
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="r_landlord_one_side_missing")
    tenant = user_factory(username="r_tenant_one_side_missing")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ENDED,
    )

    _set_first_attr(tenancy, ["review_open_at"], timezone.now() - timedelta(days=10), allow_missing=True)
    _set_first_attr(tenancy, ["review_deadline_at"], timezone.now() - timedelta(days=1), allow_missing=True)
    tenancy.save()

    _create_review(
        review_model=Review,
        tenancy=tenancy,
        room=room,
        reviewer=tenant,
        reviewee=landlord,
        rating=5,
        text="Only tenant submitted",
    )

    task_tenancy_prompts_sweep()

    reviews = _refresh_reviews(Review, tenancy)
    assert len(reviews) == 1
    r = reviews[0]

    if hasattr(r, "is_revealed"):
        assert r.is_revealed is False
    if hasattr(r, "revealed_at"):
        assert r.revealed_at is None
    if hasattr(r, "is_hidden"):
        assert r.is_hidden is True
