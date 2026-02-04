from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from drf_spectacular.renderers import OpenApiJsonRenderer


def debug_urls(request):
    """
    Temporary debug endpoint.
    Remove after Swagger is working.
    """
    return JsonResponse(
        {
            "DEBUG": settings.DEBUG,
            "ROOT_URLCONF": settings.ROOT_URLCONF,
        }
    )


urlpatterns = [
    path("admin/", admin.site.urls),

    # TEMP (remove later)
    path("debug/urls/", debug_urls),

    # API v1 (official)
    path("api/v1/", include(("propertylist_app.api.urls", "api"), namespace="v1")),

    # JWT token endpoints
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    # Schema JSON (force JSON renderer only)
   # Versioned schema (required for URLPathVersioning)
    path("api/v1/schema/", SpectacularAPIView.as_view(renderer_classes=[OpenApiJsonRenderer]),name="schema",),

    # Swagger UI pointing to VERSIONED schema
    path("api/schema/swagger-ui/",SpectacularSwaggerView.as_view(url="/api/v1/schema/"),name="swagger-ui",),


    # Redoc
    path("api/schema/redoc/",SpectacularRedocView.as_view(url_name="schema"),name="redoc",),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
