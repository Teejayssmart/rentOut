def install_room_serializer_image_cache():
    """
    Ensure RoomSerializer loads each room's image rows only once while
    building a response.

    The serializer exposes several image-derived fields from the same photo
    set. Without this request-local cache, each field repeats the identical
    RoomImage query.
    """
    from propertylist_app.api.serializers import RoomSerializer

    if getattr(RoomSerializer, "_room_image_cache_installed", False):
        return

    def _room_images(self, obj):
        cache = getattr(self, "_room_images_cache", None)
        if cache is None:
            cache = {}
            self._room_images_cache = cache

        room_key = obj.pk if obj.pk is not None else id(obj)

        if room_key not in cache:
            cache[room_key] = list(
                obj.roomimage_set.filter(
                    status__in=["approved", "pending", "rejected"]
                ).order_by("id")
            )

        return cache[room_key]

    RoomSerializer._room_images = _room_images
    RoomSerializer._room_image_cache_installed = True
