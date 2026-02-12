# property/propertylist_app/tests/reviews/test_review_xor_validation.py

from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def _get_model(app_label, model_name):
    return apps.get_model(app_label, model_name)


def _make_tenancy(room, landlord, tenant, *, status):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    now = timezone.now()

    t = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=3,
        status=status,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
    )

    # Make the review schedule "ready"
    if hasattr(t, "review_open_at"):
        t.review_open_at = now - timedelta(days=1)
    if hasattr(t, "review_deadline_at"):
        t.review_deadline_at = now + timedelta(days=7)
    t.save()

    return t


def _url(tenancy_id: int) -> str:
    return f"/api/tenancies/{tenancy_id}/reviews/"


def _auth(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_xor_rejects_flags_plus_notes(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="xor_landlord_1")
    tenant = user_factory(username="xor_tenant_1")
    room = room_factory(property_owner=landlord)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = _auth(tenant)
    payload = {"review_flags": ["responsive"], "notes": "Should not allow both."}

    res = client.post(_url(tenancy.id), data=payload, format="json")
    assert res.status_code == 400
    # reason: A4 envelope stores field-level validation errors under field_errors
    assert res.data.get("ok") is False
    assert res.data.get("code") == "validation_error"
    assert "notes" in res.data.get("field_errors", {})



def test_xor_rejects_flags_plus_overall_rating(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="xor_landlord_2")
    tenant = user_factory(username="xor_tenant_2")
    room = room_factory(property_owner=landlord)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = _auth(tenant)
    payload = {"review_flags": ["responsive"], "overall_rating": 5}

    res = client.post(_url(tenancy.id), data=payload, format="json")
    assert res.status_code == 400
    # reason: A4 envelope stores field-level validation errors under field_errors
    assert res.data.get("ok") is False
    assert res.data.get("code") == "validation_error"
    assert "overall_rating" in res.data.get("field_errors", {})



def test_xor_rejects_notes_only(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="xor_landlord_3")
    tenant = user_factory(username="xor_tenant_3")
    room = room_factory(property_owner=landlord)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = _auth(tenant)
    payload = {"notes": "Text without rating is not allowed."}

    res = client.post(_url(tenancy.id), data=payload, format="json")
    assert res.status_code == 400
    # reason: A4 envelope stores field-level validation errors under field_errors
    assert res.data.get("ok") is False
    assert res.data.get("code") == "validation_error"
    assert "overall_rating" in res.data.get("field_errors", {})



def test_xor_rejects_overall_rating_only(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="xor_landlord_4")
    tenant = user_factory(username="xor_tenant_4")
    room = room_factory(property_owner=landlord)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = _auth(tenant)
    payload = {"overall_rating": 4}

    res = client.post(_url(tenancy.id), data=payload, format="json")
    assert res.status_code == 400
    # reason: A4 envelope stores field-level validation errors under field_errors
    assert res.data.get("ok") is False
    assert res.data.get("code") == "validation_error"
    assert "notes" in res.data.get("field_errors", {})




def test_xor_rejects_neither_flags_nor_text_rating(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="xor_landlord_5")
    tenant = user_factory(username="xor_tenant_5")
    room = room_factory(property_owner=landlord)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = _auth(tenant)
    payload = {}

    res = client.post(_url(tenancy.id), data=payload, format="json")
    assert res.status_code == 400
    # Either "notes" or "overall_rating" error is acceptable depending on your validation ordering
    # reason: A4 envelope stores field-level validation errors under field_errors
    fe = res.data.get("field_errors", {})
    assert ("notes" in fe) or ("overall_rating" in fe), f"Expected notes/overall_rating error, got {res.data}"



def test_xor_allows_flags_only_checklist_mode(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="xor_landlord_6")
    tenant = user_factory(username="xor_tenant_6")
    room = room_factory(property_owner=landlord)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = _auth(tenant)
    payload = {"review_flags": ["responsive"]}

    res = client.post(_url(tenancy.id), data=payload, format="json")
    assert res.status_code in (200, 201), res.data

    review = Review.objects.filter(tenancy=tenancy).latest("id")
    assert review.review_flags == ["responsive"]
    assert review.notes in (None, "")


def test_xor_allows_notes_plus_rating_text_mode(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="xor_landlord_7")
    tenant = user_factory(username="xor_tenant_7")
    room = room_factory(property_owner=landlord)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = _auth(tenant)
    payload = {"overall_rating": 5, "notes": "Wordings must be stored exactly as typed."}

    res = client.post(_url(tenancy.id), data=payload, format="json")
    assert res.status_code in (200, 201), res.data

    review = Review.objects.filter(tenancy=tenancy).latest("id")
    assert int(review.overall_rating) == 5
    assert review.review_flags == []
    assert review.notes == "Wordings must be stored exactly as typed."


