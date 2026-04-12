
from datetime import date
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import LimitOffsetPagination





def _pagination_meta(paginator):
    """
    Build consistent pagination meta for Option A success responses.
    Works with DRF PageNumberPagination and your custom paginators.
    """
    count = None
    try:
        # DRF paginator usually has .page with a Django Paginator inside
        count = paginator.page.paginator.count
    except Exception:
        count = None

    next_link = None
    prev_link = None
    try:
        next_link = paginator.get_next_link()
        prev_link = paginator.get_previous_link()
    except Exception:
        next_link = None
        prev_link = None

    return {"count": count, "next": next_link, "previous": prev_link}


def ok_response(data, *, message=None, meta=None, status_code=200):
    """
    Standard success response envelope:
    {"ok": true, "message": <str|null>, "data": ..., "meta": ...?}

    Backwards-compatible keys for paginated list endpoints:
    - count, next, previous, results
    """
    payload = {"ok": True, "message": message, "data": data}

    if meta is not None:
        payload["meta"] = meta

        # If this looks like pagination meta and data is a list, expose DRF-style keys too.
        if isinstance(meta, dict) and isinstance(data, list) and "count" in meta:
            payload["count"] = meta.get("count")
            payload["next"] = meta.get("next")
            payload["previous"] = meta.get("previous")
            payload["results"] = data

    return Response(payload, status=status_code)






# --------------------
# A3: Consistent success response envelope (NO mixins)
# --------------------

def _wrap_success_payload(payload):
    """
    Wrap successful DRF responses into a consistent shape.

    Rules:
    - If payload is already our success envelope, do not wrap again.
    - If payload is DRF paginated (has "results"), put results into "data"
      and pagination fields into "meta", while also keeping the legacy
      pagination keys for backwards compatibility.
    - If payload is a plain list, put list into "data" and also expose
      "results" for backwards compatibility.
    - Otherwise, payload goes into "data".
    """

    # Already wrapped by ok_response(...) or similar
    if (
        isinstance(payload, dict)
        and payload.get("ok") is True
        and "data" in payload
        and "message" in payload
    ):
        data = payload.get("data")

        # If wrapped data is a plain list, keep results alias too
        if isinstance(data, list):
            payload.setdefault("results", data)

        # If wrapped data itself is paginated, flatten pagination keys too
        if isinstance(data, dict) and "results" in data:
            payload["results"] = data.get("results", [])
            payload["count"] = data.get("count")
            payload["next"] = data.get("next")
            payload["previous"] = data.get("previous")

        return payload

    # DRF paginated response
    if isinstance(payload, dict) and "results" in payload:
        results = payload.get("results", [])
        meta = {
            "count": payload.get("count"),
            "next": payload.get("next"),
            "previous": payload.get("previous"),
        }

        return {
            "ok": True,
            "message": None,
            "data": results,
            "meta": meta,
            "count": meta["count"],
            "next": meta["next"],
            "previous": meta["previous"],
            "results": results,
        }

    # Plain list response
    if isinstance(payload, list):
        return {
            "ok": True,
            "message": None,
            "data": payload,
            "results": payload,
        }

    # Non-paginated object response
    return {
        "ok": True,
        "message": None,
        "data": payload,
    }


def _wrap_response_success(response):
    """
    Mutates a DRF Response object to wrap response.data using _wrap_success_payload().
    """
    response.data = _wrap_success_payload(response.data)
    return response




def _listing_state_for_room(room):
    # hidden/unpublished overrides everything
    if getattr(room, "status", None) == "hidden":
        return "hidden"

    # no paid_until means draft
    if not room.paid_until:
        return "draft"

    # paid_until in the past means expired
    if room.paid_until < timezone.localdate():
        return "expired"

    return "active"
