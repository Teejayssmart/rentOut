# property/propertylist_app/tests/reviews/test_review_submission_permissions.py

from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def _get_model(app_label, model_name):
    return apps.get_model(app_label, model_name)


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


def _make_tenancy(room, landlord, tenant, *, status):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    now = timezone.now()

    return Tenancy.objects.create(
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


def _discover_review_create_url(client: APIClient, tenancy_id: int) -> str:
    """
    Find a URL that actually allows creating a review.

    Reason:
    During /api -> /api/v1 migration, hitting legacy paths may 308-redirect.
    Following redirects can create loops in some setups (e.g. /api/v1/v1/...).
    So we do NOT follow redirects here; instead, we normalise redirects ourselves.
    """
    candidates = [
        # Prefer v1 first
        "/api/v1/reviews/",
        "/api/v1/review/",
        f"/api/v1/tenancies/{tenancy_id}/reviews/",
        f"/api/v1/tenancies/{tenancy_id}/review/",
        f"/api/v1/tenancies/{tenancy_id}/submit-review/",
        f"/api/v1/tenancies/{tenancy_id}/review/submit/",
        f"/api/v1/tenancies/{tenancy_id}/leave-review/",

        # Legacy fallbacks (still present during migration)
        "/api/reviews/",
        "/api/review/",
        f"/api/tenancies/{tenancy_id}/reviews/",
        f"/api/tenancies/{tenancy_id}/review/",
        f"/api/tenancies/{tenancy_id}/submit-review/",
        f"/api/tenancies/{tenancy_id}/review/submit/",
        f"/api/tenancies/{tenancy_id}/leave-review/",
    ]

    def _normalise(url: str) -> str:
        # ensure trailing slash
        return url if url.endswith("/") else url + "/"

    # If we get redirected, use the Location header as the real endpoint (without following chains)
    def _redirect_target(res, fallback: str) -> str | None:
        if res.status_code in (301, 302, 307, 308):
            loc = res.headers.get("Location") or res.get("Location")
            if loc:
                return _normalise(loc)
            return _normalise(fallback)
        return None

    # Prefer OPTIONS that allows POST (but do NOT follow redirects)
    for url in candidates:
        url = _normalise(url)
        res = client.options(url, follow=False)

        redir = _redirect_target(res, url)
        if redir:
            # try OPTIONS on the target once, no follow
            res2 = client.options(redir, follow=False)
            allow2 = (res2.headers.get("Allow") or "").upper()
            if "POST" in allow2:
                return redir
            # if it’s not 404, it still “exists” as a candidate for POST probing
            if res2.status_code != 404:
                url = redir
                res = res2

        if res.status_code == 404:
            continue

        allow = (res.headers.get("Allow") or "").upper()
        if "POST" in allow:
            return url

    # Probe with a dummy POST; accept any response except 404/405 (no redirect follow)
    Review = _get_model("propertylist_app", "Review")
    dummy_payload = {
        "tenancy": tenancy_id,
        "role": getattr(Review, "ROLE_TENANT_TO_LANDLORD", "tenant_to_landlord"),
        "overall_rating": 5,
        "review_flags": [],
        "notes": "",
    }

    for url in candidates:
        url = _normalise(url)
        res = client.post(url, data=dummy_payload, format="json", follow=False)

        redir = _redirect_target(res, url)
        if redir:
            res2 = client.post(redir, data=dummy_payload, format="json", follow=False)
            if res2.status_code not in (404, 405):
                return redir
            continue

        if res.status_code not in (404, 405):
            return url

    pytest.fail(
        "Could not find a review-create endpoint that accepts POST. Tried: "
        + ", ".join(candidates)
        + ". Add your real create endpoint to candidates in _discover_review_create_url."
    )
    
    

def _build_payload(*, tenancy_id=None, role=None):
    payload = {}

    if tenancy_id is not None:
        payload["tenancy_id"] = tenancy_id
    if role is not None:
        payload["role"] = role

    # checklist mode ONLY
    payload["review_flags"] = ["responsive"]

    return payload



def test_tenant_cannot_submit_landlord_to_tenant_review(user_factory, room_factory):
    Review = _get_model("propertylist_app", "Review")
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="rp_landlord1")
    tenant = user_factory(username="rp_tenant1")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    client.force_authenticate(user=tenant)

    url = _discover_review_create_url(client, tenancy.id)
    payload = _build_payload(tenancy_id=tenancy.id, role=Review.ROLE_LANDLORD_TO_TENANT)

    res = client.post(url, data=payload, format="json")
    assert res.status_code in (400, 403)


def test_landlord_cannot_submit_tenant_to_landlord_review(user_factory, room_factory):
    Review = _get_model("propertylist_app", "Review")
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="rp_landlord2")
    tenant = user_factory(username="rp_tenant2")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    client.force_authenticate(user=landlord)

    url = _discover_review_create_url(client, tenancy.id)
    payload = _build_payload(tenancy_id=tenancy.id, role=Review.ROLE_TENANT_TO_LANDLORD)

    res = client.post(url, data=payload, format="json")
    assert res.status_code in (400, 403)


def test_random_user_cannot_submit_review_for_tenancy(user_factory, room_factory):
    Review = _get_model("propertylist_app", "Review")
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="rp_landlord3")
    tenant = user_factory(username="rp_tenant3")
    random_user = user_factory(username="rp_random3")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    client.force_authenticate(user=random_user)

    url = _discover_review_create_url(client, tenancy.id)
    payload = _build_payload(tenancy_id=tenancy.id, role=Review.ROLE_TENANT_TO_LANDLORD)

    res = client.post(url, data=payload, format="json")
    assert res.status_code in (400, 403, 404)


def test_duplicate_review_same_tenancy_and_role_is_blocked(user_factory, room_factory):
    Review = _get_model("propertylist_app", "Review")
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="rp_landlord4")
    tenant = user_factory(username="rp_tenant4")
    room = room_factory(property_owner=landlord)

    _make_booking(tenant, room)
    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ENDED)

    # Make tenancy review window ready (your API blocks reviews until schedule is ready)
    tenancy.review_open_at = timezone.now() - timedelta(days=1)
    tenancy.review_deadline_at = timezone.now() + timedelta(days=7)
    tenancy.save(update_fields=["review_open_at", "review_deadline_at"])

    client = APIClient()
    client.force_authenticate(user=tenant)

    url = _discover_review_create_url(client, tenancy.id)
    payload = _build_payload(tenancy_id=tenancy.id, role=Review.ROLE_TENANT_TO_LANDLORD)

    res1 = client.post(url, data=payload, format="json")
    assert res1.status_code in (200, 201), getattr(res1, "data", getattr(res1, "content", b"")[:2000])

    res2 = client.post(url, data=payload, format="json")
    assert res2.status_code in (400, 409)
