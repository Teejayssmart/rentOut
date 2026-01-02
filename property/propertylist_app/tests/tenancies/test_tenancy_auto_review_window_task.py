from datetime import timedelta, date

import pytest
from django.utils import timezone

from propertylist_app.models import Tenancy
from propertylist_app.tasks import task_refresh_tenancy_status_and_review_windows


pytestmark = pytest.mark.django_db


def test_task_backfills_review_window_fields_for_existing_tenancy(user_factory, room_factory):
    landlord = user_factory(username="ll_auto_dates")
    tenant = user_factory(username="tt_auto_dates")
    room = room_factory(property_owner=landlord)

    t = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=60),
        duration_months=1,
        status=Tenancy.STATUS_CONFIRMED,
        landlord_confirmed_at=timezone.now() - timedelta(days=60),
        tenant_confirmed_at=timezone.now() - timedelta(days=60),
        review_open_at=None,
        review_deadline_at=None,
        still_living_check_at=None,
    )

    task_refresh_tenancy_status_and_review_windows()

    t.refresh_from_db()
    assert t.review_open_at is not None
    assert t.review_deadline_at is not None
    assert t.still_living_check_at is not None


def test_task_marks_tenancy_ended_when_end_date_passed(user_factory, room_factory):
    landlord = user_factory(username="ll_auto_end")
    tenant = user_factory(username="tt_auto_end")
    room = room_factory(property_owner=landlord)

    t = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=120),
        duration_months=3,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=timezone.now() - timedelta(days=120),
        tenant_confirmed_at=timezone.now() - timedelta(days=120),
    )

    task_refresh_tenancy_status_and_review_windows()

    t.refresh_from_db()
    assert t.status == Tenancy.STATUS_ENDED
