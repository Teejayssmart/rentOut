from datetime import timedelta, date

import pytest
from django.utils import timezone

from propertylist_app.models import Tenancy, Review


pytestmark = pytest.mark.django_db


def test_room_rating_includes_tenancy_reviews(user_factory, room_factory):
    landlord = user_factory(username="ll_rating_tenancy")
    tenant = user_factory(username="tt_rating_tenancy")
    room = room_factory(property_owner=landlord)

    # Confirmed tenancy with review window already open (so reveal_at becomes <= now)
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=120),
        duration_months=3,
        status=Tenancy.STATUS_ENDED,
        landlord_confirmed_at=timezone.now() - timedelta(days=120),
        tenant_confirmed_at=timezone.now() - timedelta(days=120),
        review_open_at=timezone.now() - timedelta(days=5),   # already open
        review_deadline_at=timezone.now() + timedelta(days=20),
    )

    # Create a tenancy-based review (signal should recalc room rating)
    r = Review.objects.create(
        tenancy=tenancy,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["responsive", "good_communication"],
        notes="great landlord",
    )

    room.refresh_from_db()

    # Review.save() calculates overall_rating; signals should count it
    assert room.number_rating == 1
    assert room.avg_rating == float(r.overall_rating)
