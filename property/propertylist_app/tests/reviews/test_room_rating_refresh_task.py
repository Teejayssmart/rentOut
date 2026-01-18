import pytest
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from propertylist_app.models import Room, RoomCategorie, Booking, Review
from propertylist_app.tasks import task_refresh_room_ratings_nightly


pytestmark = pytest.mark.django_db


def _make_user(django_user_model, username: str):
    return django_user_model.objects.create_user(
        username=username,
        password="pass12345",
        email=f"{username}@example.com",
    )


def _make_room(*, owner, category):
    """
    Creates a Room using only the required fields from your Room model:
    title, description, price_per_month, location, category, property_owner, property_type.
    """
    return Room.objects.create(
        title="Nice room",
        description="A clean room",
        price_per_month=Decimal("500.00"),
        location="Southampton",
        category=category,
        property_owner=owner,
        property_type="flat",
    )


def _make_booking(*, user, room, start, end):
    # Booking requires: user, room, start, end
    return Booking.objects.create(
        user=user,
        room=room,
        start=start,
        end=end,
    )


def test_task_refresh_room_ratings_updates_room_for_revealed_reviews(django_user_model):
    now = timezone.now()

    landlord = _make_user(django_user_model, "landlord1")
    tenant = _make_user(django_user_model, "tenant1")

    category = RoomCategorie.objects.create(name="Standard")

    room = _make_room(owner=landlord, category=category)

    # Ensure room starts with no ratings
    room.avg_rating = 0
    room.number_rating = 0
    room.save(update_fields=["avg_rating", "number_rating"])

    booking = _make_booking(
        user=tenant,
        room=room,
        start=now - timedelta(days=3),
        end=now - timedelta(days=2),
    )

    # Create a revealed review (Option A requires reveal_at <= now)
    review = Review.objects.create(
        booking=booking,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        reveal_at=now - timedelta(days=1),
        review_flags=["responsive", "maintenance_good"],  # forces rating to 5 via save()
        notes="Good landlord",
        active=True,
    )
    review.refresh_from_db()
    assert review.overall_rating == 5

    # Run nightly refresh task
    updated_rooms_count = task_refresh_room_ratings_nightly()
    assert updated_rooms_count == 1

    # Room rating should now reflect the revealed review
    room.refresh_from_db()
    assert room.number_rating == 1
    assert room.avg_rating == pytest.approx(5.0)


def test_task_refresh_room_ratings_ignores_unrevealed_reviews(django_user_model):
    now = timezone.now()

    landlord = _make_user(django_user_model, "landlord2")
    tenant = _make_user(django_user_model, "tenant2")

    category = RoomCategorie.objects.create(name="Standard 2")

    room = _make_room(owner=landlord, category=category)

    room.avg_rating = 0
    room.number_rating = 0
    room.save(update_fields=["avg_rating", "number_rating"])

    booking = _make_booking(
        user=tenant,
        room=room,
        start=now - timedelta(days=3),
        end=now - timedelta(days=2),
    )

    # Unrevealed review: reveal_at is in the future -> should not be counted
    Review.objects.create(
        booking=booking,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        reveal_at=now + timedelta(days=10),
        review_flags=["responsive", "maintenance_good"],
        active=True,
    )

    updated_rooms_count = task_refresh_room_ratings_nightly()
    assert updated_rooms_count == 0

    room.refresh_from_db()
    assert room.number_rating == 0
    assert room.avg_rating == pytest.approx(0.0)
