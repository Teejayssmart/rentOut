from datetime import timedelta, date

import pytest
from django.utils import timezone

from propertylist_app.models import Tenancy, Review
from propertylist_app.tasks import task_tenancy_prompts_sweep
from propertylist_app.services.reviews import update_room_rating_from_revealed_reviews



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

    r = Review.objects.create(
        tenancy=tenancy,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        review_flags=["responsive", "good_communication"],
        notes="great landlord",
        active=True,
        reveal_at=timezone.now() - timedelta(days=1),
        )

    # IMPORTANT: ensure overall_rating is computed
    r.save()
    r.refresh_from_db()
    assert r.overall_rating is not None

    # Now trigger aggregation
    update_room_rating_from_revealed_reviews(room)

    room.refresh_from_db()

    assert room.number_rating == 1
    assert float(room.avg_rating) == float(r.overall_rating)

