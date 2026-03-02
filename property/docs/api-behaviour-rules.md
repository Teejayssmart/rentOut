# RentOut API Behaviour Rules (v1)

This document defines stable behaviour rules so the frontend knows what to expect.

## Pagination (all list endpoints)

### Response shape
All list endpoints that return collections should return a paginated envelope:

- `count` (int)
- `next` (url or null)
- `previous` (url or null)
- `results` (array)

Example:
```json
{
  "count": 123,
  "next": "https://.../?limit=20&offset=20",
  "previous": null,
  "results": []
}



import re
from datetime import datetime

import pytest
from rest_framework.test import APIClient

ISO8601_TZ_RE = re.compile(r".*(Z|[+-]\d{2}:\d{2})$")


def _is_iso8601_with_tz(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if not ISO8601_TZ_RE.match(value):
        return False
    # Python doesn't parse 'Z' directly; convert to +00:00
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(value)
        return True
    except Exception:
        return False


def _assert_paginated(payload: dict):
    assert isinstance(payload, dict)
    assert "count" in payload and isinstance(payload["count"], int)
    assert "results" in payload and isinstance(payload["results"], list)
    assert "next" in payload
    assert "previous" in payload


@pytest.mark.django_db
def test_h1_pagination_shape_rooms_list():
    client = APIClient()
    r = client.get("/api/v1/rooms/?limit=1&offset=0")
    assert r.status_code == 200, r.content
    _assert_paginated(r.json())


@pytest.mark.django_db
def test_h1_pagination_shape_search_rooms():
    client = APIClient()
    r = client.get("/api/v1/search/rooms/?limit=1&offset=0&q=test")
    assert r.status_code == 200, r.content
    _assert_paginated(r.json())


@pytest.mark.django_db
def test_h1_datetime_has_timezone_when_present():
    """
    This is a lightweight check: if a response includes created_at/updated_at,
    it must be ISO-8601 with timezone.
    """
    client = APIClient()
    r = client.get("/api/v1/rooms/?limit=1&offset=0")
    assert r.status_code == 200, r.content
    data = r.json()
    _assert_paginated(data)

    if not data["results"]:
        pytest.skip("No rooms returned; cannot check datetime fields.")

    item = data["results"][0]
    for key in ("created_at", "updated_at", "published_at"):
        if key in item and item[key]:
            assert _is_iso8601_with_tz(item[key]), f"{key} missing timezone: {item[key]}"
            return

    pytest.skip("No created_at/updated_at/published_at field found; update keys to match your response.")