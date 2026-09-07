"""Query optimization for booking list serialization."""

from propertylist_app.api.views.bookings import BookingListCreateView


_ORIGINAL_GET_QUERYSET = BookingListCreateView.get_queryset
_INSTALLED = False


def _optimized_get_queryset(self):
    queryset = _ORIGINAL_GET_QUERYSET(self)
    return queryset.select_related("room", "user")


def install_booking_list_query_optimization():
    """Load booking room/user rows in the same query as each booking."""
    global _INSTALLED

    if _INSTALLED:
        return

    BookingListCreateView.get_queryset = _optimized_get_queryset
    _INSTALLED = True
