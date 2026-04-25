# propertylist_app/api/pagination.py
from django.conf import settings
from rest_framework.pagination import (
    PageNumberPagination,
    LimitOffsetPagination,
    CursorPagination,
    _positive_int,
)
from rest_framework.utils.urls import replace_query_param, remove_query_param

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

    Additionally:
      - next/previous links always use canonical "offset"
      - we strip "start" from pagination links
      - we KEEP "offset=0" in previous links (your tests require it)
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

    def get_next_link(self):
        if self.count is None:
            return None

        limit = self.get_limit(self.request)
        if limit is None:
            return None

        offset = self.get_offset(self.request)
        if offset + limit >= self.count:
            return None

        url = self.request.build_absolute_uri()
        url = replace_query_param(url, self.limit_query_param, limit)
        url = replace_query_param(url, self.offset_query_param, offset + limit)

        # strip legacy param from links
        url = remove_query_param(url, "start")
        return url

    def get_previous_link(self):
        if self.count is None:
            return None

        limit = self.get_limit(self.request)
        if limit is None:
            return None

        offset = self.get_offset(self.request)
        if offset <= 0:
            return None

        prev_offset = max(offset - limit, 0)

        url = self.request.build_absolute_uri()
        url = replace_query_param(url, self.limit_query_param, limit)

        # IMPORTANT: always include offset, even when 0 (test expects offset=0)
        url = replace_query_param(url, self.offset_query_param, prev_offset)

        # strip legacy param from links
        url = remove_query_param(url, "start")
        return url