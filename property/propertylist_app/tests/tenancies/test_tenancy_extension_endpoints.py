# propertylist_app/tests/tenancies/test_tenancy_extension_endpoints.py

from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

# Reason: Your API is versioned; using /api/v1 avoids 308 redirects from /api -> /api/v1
API_BASE = "/api/v1"


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
    client.force_authenticate(user=user)


def test_extension_create_by_landlord_creates_proposal(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

    landlord = user_factory(username="ex_landlord1")
    tenant = user_factory(username="ex_tenant1")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE)

    client = APIClient()
    _auth(client, landlord)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/"
    res = client.post(url, data={"proposed_duration_months": 6}, format="json")

    assert res.status_code == 201
    assert TenancyExtension.objects.filter(tenancy=tenancy, status=TenancyExtension.STATUS_PROPOSED).count() == 1


def test_extension_create_by_tenant_creates_proposal(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

    landlord = user_factory(username="ex_landlord2")
    tenant = user_factory(username="ex_tenant2")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE)

    client = APIClient()
    _auth(client, tenant)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/"
    res = client.post(url, data={"proposed_duration_months": 9}, format="json")

    assert res.status_code == 201
    assert TenancyExtension.objects.filter(tenancy=tenancy, status=TenancyExtension.STATUS_PROPOSED).count() == 1


def test_extension_create_forbidden_for_non_party(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="ex_landlord3")
    tenant = user_factory(username="ex_tenant3")
    outsider = user_factory(username="ex_outsider3")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE)

    client = APIClient()
    _auth(client, outsider)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/"
    res = client.post(url, data={"proposed_duration_months": 6}, format="json")

    assert res.status_code == 403


def test_extension_respond_accept_updates_tenancy(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

    landlord = user_factory(username="ex_landlord4")
    tenant = user_factory(username="ex_tenant4")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE, duration_months=3)

    ext = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_duration_months=12,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    client = APIClient()
    _auth(client, tenant)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/{ext.id}/respond/"
    res = client.patch(url, data={"action": "accept"}, format="json")

    assert res.status_code == 200
    tenancy.refresh_from_db()
    assert tenancy.duration_months == 12

    ext.refresh_from_db()
    assert ext.status == TenancyExtension.STATUS_ACCEPTED
    assert ext.responded_at is not None


def test_extension_respond_reject_leaves_tenancy_unchanged(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

    landlord = user_factory(username="ex_landlord5")
    tenant = user_factory(username="ex_tenant5")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE, duration_months=3)

    ext = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_duration_months=10,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    client = APIClient()
    _auth(client, tenant)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/{ext.id}/respond/"
    res = client.patch(url, data={"action": "reject"}, format="json")

    assert res.status_code == 200
    tenancy.refresh_from_db()
    assert tenancy.duration_months == 3

    ext.refresh_from_db()
    assert ext.status == TenancyExtension.STATUS_REJECTED
    assert ext.responded_at is not None


def test_extension_respond_forbidden_for_proposer(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

    landlord = user_factory(username="ex_landlord6")
    tenant = user_factory(username="ex_tenant6")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE)

    ext = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_duration_months=8,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    client = APIClient()
    _auth(client, landlord)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/{ext.id}/respond/"
    res = client.patch(url, data={"action": "accept"}, format="json")

    assert res.status_code == 403


def test_extension_prevents_multiple_open_proposals(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

    landlord = user_factory(username="ex_landlord7")
    tenant = user_factory(username="ex_tenant7")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE)

    TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_duration_months=6,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    client = APIClient()
    _auth(client, tenant)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/"
    res = client.post(url, data={"proposed_duration_months": 9}, format="json")

    assert res.status_code == 400


def test_extension_disallowed_when_tenancy_ended(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="ex_landlord8")
    tenant = user_factory(username="ex_tenant8")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    _auth(client, landlord)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/"
    res = client.post(url, data={"proposed_duration_months": 6}, format="json")

    assert res.status_code == 400