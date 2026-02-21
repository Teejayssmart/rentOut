# propertylist_app/tests/tenancies/test_still_living_endpoints.py

from datetime import date, timedelta

from django.urls import reverse
import pytest
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _get_model(app_label: str, model_name: str):
    return __import__("django.apps").apps.apps.get_model(app_label, model_name)


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


def _make_tenancy(room, landlord, tenant, *, proposed_by, status, move_in_days_ago=90, duration_months=3):
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


def _auth(client: APIClient, user):
    # Works with DRF APIClient in pytest
    client.force_authenticate(user=user)


def _confirm_url(tenancy_id: int) -> str:
    """
    Reason:
    Your project redirects legacy /api -> canonical /api/v1 (308).
    DRF APIClient does not follow 308 redirects for PATCH by default.
    So tests must hit the canonical v1 route directly to assert real status codes.
    """
    return reverse("v1:tenancy-still-living-confirm", kwargs={"tenancy_id": tenancy_id})


def test_still_living_confirm_landlord_marks_landlord_confirmed(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_landlord")
    tenant = user_factory(username="sl_tenant")
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
    tenancy.still_living_landlord_confirmed_at = None
    tenancy.still_living_tenant_confirmed_at = None
    tenancy.save(
        update_fields=[
            "still_living_check_at",
            "still_living_confirmed_at",
            "still_living_landlord_confirmed_at",
            "still_living_tenant_confirmed_at",
        ]
    )

    client = APIClient()
    _auth(client, landlord)

    url = _confirm_url(tenancy.id)
    res = client.patch(url, data={}, format="json")

    assert res.status_code == 200
    tenancy.refresh_from_db()
    assert tenancy.still_living_landlord_confirmed_at is not None
    assert tenancy.still_living_tenant_confirmed_at is None
    assert tenancy.still_living_confirmed_at is None


def test_still_living_confirm_tenant_marks_tenant_confirmed(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_landlord2")
    tenant = user_factory(username="sl_tenant2")
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
    tenancy.still_living_landlord_confirmed_at = None
    tenancy.still_living_tenant_confirmed_at = None
    tenancy.save(
        update_fields=[
            "still_living_check_at",
            "still_living_confirmed_at",
            "still_living_landlord_confirmed_at",
            "still_living_tenant_confirmed_at",
        ]
    )

    client = APIClient()
    _auth(client, tenant)

    url = _confirm_url(tenancy.id)
    res = client.patch(url, data={}, format="json")

    assert res.status_code == 200
    tenancy.refresh_from_db()
    assert tenancy.still_living_tenant_confirmed_at is not None
    assert tenancy.still_living_landlord_confirmed_at is None
    assert tenancy.still_living_confirmed_at is None


def test_still_living_confirm_second_party_sets_still_living_confirmed_at(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_landlord3")
    tenant = user_factory(username="sl_tenant3")
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
    tenancy.still_living_landlord_confirmed_at = timezone.now() - timedelta(hours=1)
    tenancy.still_living_tenant_confirmed_at = None
    tenancy.save(
        update_fields=[
            "still_living_check_at",
            "still_living_confirmed_at",
            "still_living_landlord_confirmed_at",
            "still_living_tenant_confirmed_at",
        ]
    )

    client = APIClient()
    _auth(client, tenant)

    url = _confirm_url(tenancy.id)
    res = client.patch(url, data={}, format="json")

    assert res.status_code == 200
    tenancy.refresh_from_db()
    assert tenancy.still_living_landlord_confirmed_at is not None
    assert tenancy.still_living_tenant_confirmed_at is not None
    assert tenancy.still_living_confirmed_at is not None


def test_still_living_confirm_is_idempotent(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_landlord4")
    tenant = user_factory(username="sl_tenant4")
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
    tenancy.save(update_fields=["still_living_check_at"])

    client = APIClient()
    _auth(client, landlord)

    url = _confirm_url(tenancy.id)
    res1 = client.patch(url, data={}, format="json")
    res2 = client.patch(url, data={}, format="json")

    assert res1.status_code == 200
    assert res2.status_code == 200


def test_still_living_confirm_rejects_if_not_due(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_landlord5")
    tenant = user_factory(username="sl_tenant5")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
    )
    tenancy.still_living_check_at = timezone.now() + timedelta(days=1)
    tenancy.save(update_fields=["still_living_check_at"])

    client = APIClient()
    _auth(client, landlord)

    url = _confirm_url(tenancy.id)
    res = client.patch(url, data={}, format="json")

    assert res.status_code == 400


def test_still_living_confirm_forbidden_for_non_party(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_landlord6")
    tenant = user_factory(username="sl_tenant6")
    outsider = user_factory(username="sl_outsider")
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
    tenancy.save(update_fields=["still_living_check_at"])

    client = APIClient()
    _auth(client, outsider)

    url = _confirm_url(tenancy.id)
    res = client.patch(url, data={}, format="json")

    assert res.status_code == 403


def test_still_living_confirm_rejects_if_tenancy_not_active(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="sl_landlord7")
    tenant = user_factory(username="sl_tenant7")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ENDED,
    )
    tenancy.still_living_check_at = timezone.now() - timedelta(days=1)
    tenancy.save(update_fields=["still_living_check_at"])

    client = APIClient()
    _auth(client, landlord)

    url = _confirm_url(tenancy.id)
    res = client.patch(url, data={}, format="json")

    assert res.status_code == 400