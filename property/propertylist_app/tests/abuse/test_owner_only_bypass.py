import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_tenant_cannot_access_owner_only_endpoint(user_factory, room_factory):
    """
    Abuse pattern:
    - tenant attempts to call a landlord/owner-only endpoint for a room they do not own.
    Proves permission enforcement across modules.
    """
    landlord = user_factory(username="own_landlord", role="landlord")
    tenant = user_factory(username="own_tenant", role="seeker")
    room = room_factory(property_owner=landlord)

    client = APIClient()
    client.force_authenticate(user=tenant)

    # REQUIRED: confirm an owner-only endpoint once you upload api/urls.py
    # Common ones: publish/unpublish, delete room, upload photo, create checkout session.
   
    owner_only_url = f"/api/v1/rooms/{room.id}/unpublish/"

    r = client.post(owner_only_url, data={}, format="json")
    assert r.status_code in (403, 404)
