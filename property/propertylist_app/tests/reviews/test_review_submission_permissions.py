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

    if hasattr(t, "review_open_at"):
        t.review_open_at = now - timedelta(days=1)
    if hasattr(t, "review_deadline_at"):
        t.review_deadline_at = now + timedelta(days=7)
    t.save()

    return t


def _reviews_create_url():
    return "/api/v1/reviews/create/"


def test_tenant_payload_cannot_force_landlord_role(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rp_landlord1")
    tenant = user_factory(username="rp_tenant1")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    client.force_authenticate(user=tenant)

    payload = {
        "tenancy_id": tenancy.id,
        "role": Review.ROLE_LANDLORD_TO_TENANT,  # wrong on purpose
        "overall_rating": 4,
        "notes": "Trying wrong role",
    }

    res = client.post(_reviews_create_url(), data=payload, format="json")
    assert res.status_code in (200, 201), getattr(res, "data", None)

    created = Review.objects.get(tenancy=tenancy, reviewer=tenant)
    assert created.role == Review.ROLE_TENANT_TO_LANDLORD
    assert created.reviewee_id == landlord.id
    assert created.reviewer_id == tenant.id
    assert int(created.overall_rating) == 4


def test_landlord_payload_cannot_force_tenant_role(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rp_landlord2")
    tenant = user_factory(username="rp_tenant2")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    client.force_authenticate(user=landlord)

    payload = {
        "tenancy_id": tenancy.id,
        "role": Review.ROLE_TENANT_TO_LANDLORD,  # wrong on purpose
        "overall_rating": 4,
        "notes": "Trying wrong role",
    }

    res = client.post(_reviews_create_url(), data=payload, format="json")
    assert res.status_code in (200, 201), getattr(res, "data", None)

    created = Review.objects.get(tenancy=tenancy, reviewer=landlord)
    assert created.role == Review.ROLE_LANDLORD_TO_TENANT
    assert created.reviewee_id == tenant.id
    assert created.reviewer_id == landlord.id
    assert int(created.overall_rating) == 4


def test_random_user_cannot_submit_review_for_tenancy(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="rp_landlord3")
    tenant = user_factory(username="rp_tenant3")
    stranger = user_factory(username="rp_stranger3")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    client.force_authenticate(user=stranger)

    payload = {
        "tenancy_id": tenancy.id,
        "role": Review.ROLE_TENANT_TO_LANDLORD,
        "overall_rating": 1,
        "notes": "Not a party to this tenancy",
    }

    res = client.post(_reviews_create_url(), data=payload, format="json")
    assert res.status_code in (400, 403, 404), getattr(res, "data", None)

    assert not Review.objects.filter(tenancy=tenancy).exists()
    
    
def test_tenant_cannot_submit_landlord_to_tenant_review_flags(
    user_factory,
    room_factory,
):
    Tenancy = __import__("django.apps").apps.apps.get_model(
        "propertylist_app",
        "Tenancy",
    )

    landlord = user_factory(username="role_flag_landlord_1")
    tenant = user_factory(username="role_flag_tenant_1")
    room = room_factory(property_owner=landlord)

    now = timezone.now()

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=timezone.localdate() - timedelta(days=90),
        duration_months=3,
        status=Tenancy.STATUS_ENDED,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
        review_open_at=now - timedelta(days=1),
        review_deadline_at=now + timedelta(days=30),
    )

    client = APIClient()
    client.force_authenticate(user=tenant)

    response = client.post(
        "/api/v1/reviews/create/",
        {
            "tenancy_id": tenancy.id,
            "review_flags": ["friendly"],
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "validation_error"
    assert "review_flags" in response.data["field_errors"]
    assert (
        "Invalid review flag(s) for tenant_to_landlord: friendly"
        in response.data["field_errors"]["review_flags"]
    )


def test_landlord_cannot_submit_tenant_to_landlord_review_flags(
    user_factory,
    room_factory,
):
    Tenancy = __import__("django.apps").apps.apps.get_model(
        "propertylist_app",
        "Tenancy",
    )

    landlord = user_factory(username="role_flag_landlord_2")
    tenant = user_factory(username="role_flag_tenant_2")
    room = room_factory(property_owner=landlord)

    now = timezone.now()

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=timezone.localdate() - timedelta(days=90),
        duration_months=3,
        status=Tenancy.STATUS_ENDED,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
        review_open_at=now - timedelta(days=1),
        review_deadline_at=now + timedelta(days=30),
    )

    client = APIClient()
    client.force_authenticate(user=landlord)

    response = client.post(
        "/api/v1/reviews/create/",
        {
            "tenancy_id": tenancy.id,
            "review_flags": ["responsive"],
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "validation_error"
    assert "review_flags" in response.data["field_errors"]
    assert (
        "Invalid review flag(s) for landlord_to_tenant: responsive"
        in response.data["field_errors"]["review_flags"]
    ) 
    
    
def test_random_user_cannot_view_revealed_review_detail(
    user_factory,
    room_factory,
):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    Review = _get_model("propertylist_app", "Review")

    landlord = user_factory(username="review_detail_landlord")
    tenant = user_factory(username="review_detail_tenant")
    stranger = user_factory(username="review_detail_stranger")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(
        room,
        landlord,
        tenant,
        status=Tenancy.STATUS_ENDED,
    )

    review = Review.objects.create(
        tenancy=tenancy,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        overall_rating=4,
        notes="Private revealed review",
        active=True,
        reveal_at=timezone.now() - timedelta(minutes=1),
    )

    client = APIClient()
    client.force_authenticate(user=stranger)

    response = client.get(
        f"/api/v1/reviews/{review.id}/"
    )

    assert response.status_code == 403    