from django.apps import AppConfig

class PropertylistAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "propertylist_app"

    def ready(self):
        # import signals so receivers are registered
        from . import signals  # noqa: F401
