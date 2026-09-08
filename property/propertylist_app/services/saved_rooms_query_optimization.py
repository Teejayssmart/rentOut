from functools import wraps


def install_saved_rooms_related_query_optimization():
    """Fetch saved-room owners and profiles with the room queryset."""
    from propertylist_app.api.views.messaging import MySavedRoomsView

    if getattr(MySavedRoomsView, "_related_query_optimized", False):
        return

    original_get_queryset = MySavedRoomsView.get_queryset

    @wraps(original_get_queryset)
    def get_queryset(self):
        queryset = original_get_queryset(self)
        return queryset.select_related(
            "property_owner",
            "property_owner__profile",
        )

    MySavedRoomsView.get_queryset = get_queryset
    MySavedRoomsView._related_query_optimized = True
