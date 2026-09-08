"""Query optimization for the authenticated user's room list."""

from propertylist_app.api.views.rooms import MyRoomsView


_ORIGINAL_GET_QUERYSET = MyRoomsView.get_queryset
_INSTALLED = False


def _optimized_get_queryset(self):
    queryset = _ORIGINAL_GET_QUERYSET(self)
    return queryset.select_related(
        "property_owner",
        "property_owner__profile",
    )


def install_my_rooms_related_query_optimization():
    """Load each room's owner/profile in the same query as the rooms."""
    global _INSTALLED

    if _INSTALLED:
        return

    MyRoomsView.get_queryset = _optimized_get_queryset
    _INSTALLED = True
