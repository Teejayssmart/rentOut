import pytest
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from propertylist_app.models import Booking, Room, Review, RoomCategorie


pytestmark = pytest.mark.django_db


def make_user(email="u@example.com", password="pass12345", username=None):
    User = get_user_model()
    if username is None:
        username = email.split("@")[0]
    return User.objects.create_user(username=username, email=email, password=password)


def make_category(name="Test Category"):
    """
    Create RoomCategorie with whatever fields your model requires.
    (Your migrations suggest at least 'name', and possibly 'about'.)
    """
    kwargs = {"name": name}

    # If the model has an 'about' field and it is required, set it.
    try:
        about_field = RoomCategorie._meta.get_field("about")
        # Only set if not nullable/blank and no default
        if not about_field.null and not about_field.blank and about_field.default is about_field.NOT_PROVIDED:
            kwargs["about"] = "Test category about"
        else:
            # safe to set anyway
            kwargs["about"] = "Test category about"
    except Exception:
        pass

    return RoomCategorie.objects.create(**kwargs)


def make_room(owner):
    # Pick a valid property_type value from your model choices
    property_type_field = Room._meta.get_field("property_type")
    property_type_value = property_type_field.choices[0][0] if property_type_field.choices else "flat"

    category = make_category()

    return Room.objects.create(
        property_owner=owner,
        category=category,
        title="Test room",
        description="Test description",
        location="Southampton",
        property_type=property_type_value,
        price_per_month=1000,
    )


def make_booking(room, tenant, end_dt):
    start_dt = end_dt - timedelta(days=30)
    return Booking.objects.create(room=room, user=tenant, start=start_dt, end=end_dt)


def profile_list_url(user_id, for_param):
    return f"/api/v1/users/{user_id}/reviews/?for={for_param}"


def summary_url(user_id):
    return f"/api/v1/users/{user_id}/review-summary/"


def test_profile_list_shows_revealed_only_and_filters_landlord_vs_tenant():
    landlord = make_user("landlord_p@example.com")
    tenant = make_user("tenant_p@example.com")

    room = make_room(owner=landlord)

    # revealed booking: end is 31 days ago => reveal_at is in the past
    booking_revealed = make_booking(
        room=room,
        tenant=tenant,
        end_dt=timezone.now() - timedelta(days=31),
    )
    Review.objects.create(
        booking=booking_revealed,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["responsive"],
        notes="revealed about landlord",
    )

    # not revealed booking: end is 1 day ago => reveal_at in the future
    booking_hidden = make_booking(
        room=room,
        tenant=tenant,
        end_dt=timezone.now() - timedelta(days=1),
    )
    Review.objects.create(
        booking=booking_hidden,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["responsive"],
        notes="hidden about landlord",
    )

    client = APIClient()

    # should show only 1 revealed landlord review
    res = client.get(profile_list_url(landlord.id, "landlord"))
    assert res.status_code == 200
    assert len(res.data["results"]) == 1



    # tenant side for landlord should be empty
    res2 = client.get(profile_list_url(landlord.id, "tenant"))
    assert res2.status_code == 200
    assert len(res2.data["results"]) == 0



def test_summary_endpoint_counts_and_averages_revealed_only():
    landlord = make_user("landlord_s@example.com")
    tenant = make_user("tenant_s@example.com")
    room = make_room(owner=landlord)

    booking1 = make_booking(room=room, tenant=tenant, end_dt=timezone.now() - timedelta(days=31))
    r1 = Review.objects.create(
        booking=booking1,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["responsive", "maintenance_good"],
        notes="good",
    )

    booking2 = make_booking(room=room, tenant=tenant, end_dt=timezone.now() - timedelta(days=31))
    r2 = Review.objects.create(
        booking=booking2,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["unresponsive"],
        notes="bad",
    )

    # hidden review should not count
    booking3 = make_booking(room=room, tenant=tenant, end_dt=timezone.now() - timedelta(days=1))
    Review.objects.create(
        booking=booking3,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["responsive"],
        notes="hidden",
    )

    r1.refresh_from_db()
    r2.refresh_from_db()

    client = APIClient()
    res = client.get(summary_url(landlord.id))
    assert res.status_code == 200

    assert res.data["landlord_count"] == 2
    assert res.data["tenant_count"] == 0
    assert res.data["landlord_average"] is not None
