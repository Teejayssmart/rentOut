# propertylist_app/api/pagination.py

from django.conf import settings
from rest_framework.pagination import (
    PageNumberPagination,
    LimitOffsetPagination,
    CursorPagination,
    _positive_int,
)


class RoomPagination(PageNumberPagination):
    page_size = 2
    page_query_param = "p"
    page_size_query_param = "size"
    max_page_size = 3
    last_page_strings = "end"


class RoomCPagination(CursorPagination):
    page_size = 5
    ordering = "created"
    cursor_query_param = "record"


class StandardLimitOffsetPagination(LimitOffsetPagination):
    """
    Standard pagination across the API.

    Canonical:
      ?limit=..&offset=..

    Backwards compatible:
      ?start=..   (treated as offset)
    """

    limit_query_param = "limit"
    offset_query_param = "offset"

    default_limit = getattr(settings, "REST_FRAMEWORK", {}).get("PAGE_SIZE", 20)
    max_limit = 100

    def get_offset(self, request):
        # canonical offset
        if "offset" in request.query_params:
            return _positive_int(request.query_params["offset"])

        # legacy alias: start -> offset
        if "start" in request.query_params:
            return _positive_int(request.query_params["start"])

        return 0