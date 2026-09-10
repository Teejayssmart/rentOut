"""Query optimization for room detail retrieval."""

from django.shortcuts import get_object_or_404

from propertylist_app.api.views.rooms import RoomDetailAV
from propertylist_app.models import Room


_INSTALLED = False


def _optimized_get_room(self, request, pk):
    """Fetch the room with serializer-related foreign keys already joined."""
    related = (
        "category",
        "property_owner",
        "property_owner__profile",
    )

    if request.user.is_authenticated:
        owned_room = (
            Room.objects.filter(
                pk=pk,
                property_owner=request.user,
                is_deleted=False,
            )
            .select_related(*related)
            .first()
        )

        if owned_room is not None:
            return owned_room

    return get_object_or_404(
        Room.objects.alive().select_related(*related),
        pk=pk,
    )


def install_room_detail_query_optimization():
    """Install the optimized room-detail lookup once at application startup."""
    global _INSTALLED

    if _INSTALLED:
        return

    RoomDetailAV._get_room = _optimized_get_room
    _INSTALLED = True
