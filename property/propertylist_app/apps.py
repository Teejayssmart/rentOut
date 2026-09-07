from django.apps import AppConfig

class PropertylistAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "propertylist_app"

    def ready(self):
        # import signals so receivers are registered
        from . import signals  # noqa: F401
        from .services.room_serializer_cache import install_room_serializer_image_cache
        from .services.homepage_query_optimization import (
            install_homepage_owner_profile_query_optimization,
        )
        from .services.saved_rooms_query_optimization import (
            install_saved_rooms_related_query_optimization,
        )
        from .services.availability_query_optimization import (
            install_availability_only_free_query_optimization,
        )
        from .services.booking_list_query_optimization import (
            install_booking_list_query_optimization,
        )

        install_room_serializer_image_cache()
        install_homepage_owner_profile_query_optimization()
        install_saved_rooms_related_query_optimization()
        install_availability_only_free_query_optimization()
        install_booking_list_query_optimization()
