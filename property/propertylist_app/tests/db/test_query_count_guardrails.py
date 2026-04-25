import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _auth(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _assert_queries_at_most(max_queries: int, fn, *, label: str):
    with CaptureQueriesContext(connection) as ctx:
        fn()
    assert len(ctx) <= max_queries, {
        "label": label,
        "max_queries": max_queries,
        "actual_queries": len(ctx),
        "queries": [q["sql"] for q in ctx.captured_queries],
    }


def test_search_rooms_query_count_guardrail(user_factory, room_factory):
    """
    Guardrail: /api/v1/search/rooms/ should remain efficient as listings grow.
    Asserts query count does NOT exceed threshold (prevents N+1 regressions).
    """
    landlord = user_factory(username="qc_landlord1", role="landlord")
    for i in range(25):
        room_factory(property_owner=landlord, title=f"QC Room {i}")

    seeker = user_factory(username="qc_seeker1", role="seeker")
    client = _auth(seeker)

    def call():
        res = client.get("/api/v1/search/rooms/")
        assert res.status_code == 200

    _assert_queries_at_most(80, call, label="GET /api/v1/search/rooms/")


def test_notifications_query_count_guardrail(user_factory):
    """
    Guardrail: /api/notifications/ should remain query-efficient.
    """
    user = user_factory(username="qc_user2", role="seeker")
    client = _auth(user)

    def call():
        res = client.get("/api/v1/notifications/")
        assert res.status_code == 200

    _assert_queries_at_most(80, call, label="GET /api/v1/notifications/")


def test_threads_list_query_count_guardrail(user_factory):
    """
    Guardrail: /api/messages/threads/ should not do N+1 queries per thread.
    """
    user = user_factory(username="qc_user3", role="seeker")
    client = _auth(user)

    def call():
        res = client.get("/api/v1/messages/threads/")
        assert res.status_code in (200, 204)

    _assert_queries_at_most(60, call, label="GET /api/v1/messages/threads/")
