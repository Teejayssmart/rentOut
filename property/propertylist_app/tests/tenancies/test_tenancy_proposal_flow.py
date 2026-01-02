import pytest
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from rest_framework.test import APIClient

from propertylist_app.models import RoomCategorie, Room, Booking

# IMPORTANT: once you add Tenancy model, this import must work
from propertylist_app.models import Tenancy


pytestmark = pytest.mark.django_db

API_PREFIX = "/api"


def _api_client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_user(username: str):
    User = get_user_model()
    return User.objects.create_user(
        username=username,
        password="pass12345",
        email=f"{username}@example.com",
    )


def _make_room(owner):
    cat = RoomCategorie.objects.create(name="Standard")
    return Room.objects.create(
        title="Nice room",
        description="Clean room",
        price_per_month="500.00",
        location="Southampton",
        category=cat,
        furnished=False,
        bills_included=False,
        property_owner=owner,
        property_type="flat",
    )


def _make_viewing_booking(user, room):
    now = timezone.now()
    return Booking.objects.create(
        user=user,
        room=room,
        start=now - timedelta(days=2),
        end=now - timedelta(days=2, minutes=-30),  # 30 mins after start, still in the past
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )



def test_landlord_proposes_tenancy_creates_single_proposal_row():
    landlord = _make_user("landlord_a")
    tenant = _make_user("tenant_a")
    room = _make_room(owner=landlord)

    # viewing exists (relationship proof)
    _make_viewing_booking(user=tenant, room=room)

    client = _api_client_for(landlord)

    payload = {
        "room_id": room.id,
        "counterparty_user_id": tenant.id,
        "move_in_date": str(date.today() + timedelta(days=7)),
        "duration_months": 6,
    }

    resp = client.post(f"{API_PREFIX}/tenancies/propose/", data=payload, format="json")
    assert resp.status_code == 201, resp.data

    tenancy_id = resp.data["id"]
    tenancy = Tenancy.objects.get(id=tenancy_id)

    assert tenancy.room_id == room.id
    assert tenancy.landlord_id == landlord.id
    assert tenancy.tenant_id == tenant.id
    assert tenancy.proposed_by_id == landlord.id
    assert tenancy.status == Tenancy.STATUS_PROPOSED

    # landlord initiated, so landlord_confirmed_at should be set (as per our planned logic)
    assert tenancy.landlord_confirmed_at is not None
    assert tenancy.tenant_confirmed_at is None

    # proposing again should reuse same tenancy row (no duplicates)
    resp2 = client.post(f"{API_PREFIX}/tenancies/propose/", data=payload, format="json")
    assert resp2.status_code in (200, 201), resp2.data

    assert Tenancy.objects.filter(room=room, tenant=tenant).count() == 1


def test_tenant_can_propose_tenancy_when_landlord_is_busy():
    landlord = _make_user("landlord_b")
    tenant = _make_user("tenant_b")
    room = _make_room(owner=landlord)

    # viewing exists (relationship proof)
    _make_viewing_booking(user=tenant, room=room)

    client = _api_client_for(tenant)

    payload = {
        "room_id": room.id,
        "counterparty_user_id": landlord.id,  # tenant proposes to landlord (room owner)
        "move_in_date": str(date.today() + timedelta(days=10)),
        "duration_months": 3,
    }

    resp = client.post(f"{API_PREFIX}/tenancies/propose/", data=payload, format="json")
    assert resp.status_code == 201, resp.data

    tenancy = Tenancy.objects.get(id=resp.data["id"])
    assert tenancy.landlord_id == landlord.id
    assert tenancy.tenant_id == tenant.id
    assert tenancy.proposed_by_id == tenant.id
    assert tenancy.status == Tenancy.STATUS_PROPOSED

    # tenant initiated; by design, tenant_confirmed_at set, landlord_confirmed_at None
    assert tenancy.tenant_confirmed_at is not None
    assert tenancy.landlord_confirmed_at is None


def test_propose_changes_resets_confirmations_and_updates_dates():
    landlord = _make_user("landlord_c")
    tenant = _make_user("tenant_c")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    # landlord proposes
    resp = landlord_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    tenancy_id = resp.data["id"]

    # tenant proposes changes
    resp2 = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={
            "action": "propose_changes",
            "move_in_date": str(date.today() + timedelta(days=14)),
            "duration_months": 12,
        },
        format="json",
    )
    assert resp2.status_code == 200, resp2.data

    tenancy = Tenancy.objects.get(id=tenancy_id)
    assert tenancy.proposed_by_id == tenant.id
    assert str(tenancy.move_in_date) == str(date.today() + timedelta(days=14))
    assert tenancy.duration_months == 12

    # confirmations reset
    assert tenancy.landlord_confirmed_at is None
    assert tenancy.tenant_confirmed_at is None
    assert tenancy.status == Tenancy.STATUS_PROPOSED


def test_both_confirm_locks_schedule_and_sets_review_dates():
    landlord = _make_user("landlord_d")
    tenant = _make_user("tenant_d")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    # landlord proposes
    resp = landlord_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=5)),
            "duration_months": 6,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    tenancy_id = resp.data["id"]

    # tenant confirms
    resp2 = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={"action": "confirm"},
        format="json",
    )
    assert resp2.status_code == 200, resp2.data

    tenancy = Tenancy.objects.get(id=tenancy_id)

    # after both confirmed, tenancy should have schedule fields
    assert tenancy.landlord_confirmed_at is not None
    assert tenancy.tenant_confirmed_at is not None
    assert tenancy.status in {Tenancy.STATUS_CONFIRMED, Tenancy.STATUS_ACTIVE}

    assert tenancy.review_open_at is not None
    assert tenancy.still_living_check_at is not None


def test_two_sided_proposals_do_not_create_two_rows_last_write_wins():
    landlord = _make_user("landlord_e")
    tenant = _make_user("tenant_e")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    # tenant proposes first
    resp1 = tenant_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": landlord.id,
            "move_in_date": str(date.today() + timedelta(days=10)),
            "duration_months": 3,
        },
        format="json",
    )
    assert resp1.status_code == 201, resp1.data
    tenancy_id = resp1.data["id"]

    # landlord proposes "at the same time" (second write)
    resp2 = landlord_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )
    assert resp2.status_code in (200, 201), resp2.data

    assert Tenancy.objects.filter(room=room, tenant=tenant).count() == 1

    tenancy = Tenancy.objects.get(id=tenancy_id)
    # After landlord overwrote, proposal terms should match landlord payload
    assert str(tenancy.move_in_date) == str(date.today() + timedelta(days=7))
    assert tenancy.duration_months == 6
