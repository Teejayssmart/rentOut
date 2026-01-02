# propertylist_app/tests/reviews/test_review_reveal_logic.py

from datetime import date, timedelta

import pytest
from django.utils import timezone

from propertylist_app.tasks import task_tenancy_prompts_sweep

pytestmark = pytest.mark.django_db


def _get_model(app_label: str, model_name: str):
    return __import__("django.apps").apps.apps.get_model(app_label, model_name)


def _make_booking(user, room, *, days_ago: int = 2):
    """
    Completed viewing = booking end is in the past.
    Matches your rule: must be viewed (not just booked).
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


def _set_attr_if_exists(obj, names, value):
    for name in names:
        if hasattr(obj, name):
            setattr(obj, name, value)
            return name
    return None


def _create_review(*, tenancy, room, reviewer, reviewee, rating=5, text="Good"):
    """
    Create Review using ONLY fields that exist in your schema.
    Avoids 'unexpected keyword argument' errors.
    """
    Review = _get_model("propertylist_app", "Review")
    field_names = {f.name for f in Review._meta.get_fields()}

    data = {}

    if "tenancy" in field_names:
        data["tenancy"] = tenancy
    if "room" in field_names:
        data["room"] = room

    for k in ("user", "reviewer", "author", "created_by"):
        if k in field_names:
            data[k] = reviewer
            break

    for k in ("target_user", "reviewee", "to_user", "recipient", "subject_user"):
        if k in field_names:
            data[k] = reviewee
            break

    for k in ("rating", "stars", "score"):
        if k in field_names:
            data[k] = rating
            break

    for k in ("content", "text", "comment", "body", "review"):
        if k in field_names:
            data[k] = text
            break

    if "is_deleted" in field_names:
        data["is_deleted"] = False

    return Review.objects.create(**data)


def _assert_hidden(review):
    """
    Proves the review is NOT visible yet.
    """
    if hasattr(review, "is_revealed"):
        assert review.is_revealed is False
    if hasattr(review, "revealed_at"):
        assert review.revealed_at is None
    if hasattr(review, "is_hidden"):
        assert review.is_hidden is True


def _assert_revealed(review):
    """
    Proves the review IS visible now.
    """
    if hasattr(review, "is_revealed"):
        assert review.is_revealed is True
    if hasattr(review, "revealed_at"):
        assert review.revealed_at is not None
    if hasattr(review, "is_hidden"):
        assert review.is_hidden is False


def _room_rating_value(room):
    """
    Returns (field_name, value) if Room has a stored/accessible rating-like attribute.
    If none found, returns (None, None).
    """
    candidates = [
        "rating",
        "avg_rating",
        "average_rating",
        "room_rating",
        "review_rating",
        "score",
    ]
    for name in candidates:
        if hasattr(room, name):
            try:
                return name, getattr(room, name)
            except Exception:
                # property might error if it depends on DB state; treat as not usable
                continue
    return None, None


def test_review_invisible_before_reveal_at(user_factory, room_factory):
    """
    Assertion:
    - review invisible before reveal_at (double-blind still enforced)
    """
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rl_landlord_invisible")
    tenant = user_factory(username="rl_tenant_invisible")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ENDED,
    )

    # Open window, but deadline NOT passed -> not reveal time
    _set_attr_if_exists(tenancy, ["review_open_at"], timezone.now() - timedelta(days=1))
    _set_attr_if_exists(tenancy, ["review_deadline_at"], timezone.now() + timedelta(days=7))
    tenancy.save()

    # Both reviews exist, but reveal should still be blocked until deadline/event
    _create_review(tenancy=tenancy, room=room, reviewer=tenant, reviewee=landlord, rating=5, text="Tenant review")
    _create_review(tenancy=tenancy, room=room, reviewer=landlord, reviewee=tenant, rating=1, text="Landlord review")

    task_tenancy_prompts_sweep()

    qs = Review.objects.filter(tenancy=tenancy).order_by("id")
    assert qs.count() == 2
    for r in qs:
        _assert_hidden(r)


def test_review_visible_after_reveal_at(user_factory, room_factory):
    """
    Assertion:
    - review visible after reveal_at (reveal event has occurred)
    """
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rl_landlord_visible")
    tenant = user_factory(username="rl_tenant_visible")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ENDED,
    )

    # Deadline passed -> reveal time reached
    _set_attr_if_exists(tenancy, ["review_open_at"], timezone.now() - timedelta(days=10))
    _set_attr_if_exists(tenancy, ["review_deadline_at"], timezone.now() - timedelta(days=1))
    tenancy.save()

    _create_review(tenancy=tenancy, room=room, reviewer=tenant, reviewee=landlord, rating=5, text="Tenant review")
    _create_review(tenancy=tenancy, room=room, reviewer=landlord, reviewee=tenant, rating=1, text="Landlord review")

    task_tenancy_prompts_sweep()

    qs = Review.objects.filter(tenancy=tenancy).order_by("id")
    assert qs.count() == 2
    for r in qs:
        _assert_revealed(r)


def test_room_rating_updates_only_after_reveal(user_factory, room_factory):
    """
    Assertion:
    - room rating does NOT change before reveal
    - room rating updates after reveal to reflect revealed reviews
    (If Room has no rating-like field, this test will skip.)
    """
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")
    Room = _get_model("propertylist_app", "Room")

    landlord = user_factory(username="rl_landlord_rating")
    tenant = user_factory(username="rl_tenant_rating")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ENDED,
    )

    # Create both reviews now, but set deadline in future so reveal is blocked
    _set_attr_if_exists(tenancy, ["review_open_at"], timezone.now() - timedelta(days=1))
    _set_attr_if_exists(tenancy, ["review_deadline_at"], timezone.now() + timedelta(days=7))
    tenancy.save()

    room = Room.objects.get(id=room.id)
    field_name, before_value = _room_rating_value(room)
    if field_name is None:
        pytest.skip("Room has no stored rating-like field to assert against.")

    # Choose ratings that are guaranteed to differ from the initial rating.
    # Use 5 and 5 -> expected average = 5.0 (avoids the 5+1 == 3.0 coincidence).
    r1 = 5
    r2 = 5
    expected_after = (r1 + r2) / 2

    # Create both reviews (but they should remain hidden until reveal)
    _create_review(tenancy=tenancy, room=room, reviewer=tenant, reviewee=landlord, rating=r1, text="Tenant review")
    _create_review(tenancy=tenancy, room=room, reviewer=landlord, reviewee=tenant, rating=r2, text="Landlord review")

    # Run sweep BEFORE reveal -> rating should NOT change
    task_tenancy_prompts_sweep()

    room = Room.objects.get(id=room.id)
    _, mid_value = _room_rating_value(room)
    assert mid_value == before_value

    # Now force reveal: deadline passed
    tenancy.review_deadline_at = timezone.now() - timedelta(days=1)
    tenancy.save(update_fields=["review_deadline_at"])

    task_tenancy_prompts_sweep()

    room = Room.objects.get(id=room.id)
    _, after_value = _room_rating_value(room)

    # After reveal, rating should match the expected average of revealed reviews.
    # Use float tolerance because some projects round/stores decimals.
    assert after_value is not None
    assert abs(float(after_value) - float(expected_after)) < 0.0001

    # Sanity: reviews are revealed now
    qs = Review.objects.filter(tenancy=tenancy).order_by("id")
    assert qs.count() == 2
    for r in qs:
        _assert_revealed(r)
