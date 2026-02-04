from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.shortcuts import redirect

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


def debug_urls(request):
    return JsonResponse(
        {
            "DEBUG": settings.DEBUG,
            "ROOT_URLCONF": settings.ROOT_URLCONF,
        }
    )


urlpatterns = [
    path("admin/", admin.site.urls),

    # TEMP: keep for troubleshooting (remove later)
    path("debug/urls/", debug_urls),

    # API v1 (your actual app endpoints)
    path("api/v1/", include(("propertylist_app.api.urls", "api"), namespace="v1")),

    # JWT token endpoints (unversioned)
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    # ✅ Schema + docs (MUST capture `version` kwarg for URLPathVersioning)
    re_path(
        r"^api/(?P<version>v1)/schema/$",
        SpectacularAPIView.as_view(),
        name="schema",
    ),
    re_path(
        r"^api/(?P<version>v1)/schema/swagger-ui/$",
        SpectacularSwaggerView.as_view(url="/api/v1/schema/"),
        name="swagger-ui",
    ),
    re_path(
        r"^api/(?P<version>v1)/schema/redoc/$",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),

    # Optional: redirect old links to the new correct location
    path("api/schema/swagger-ui/", lambda r: redirect("/api/v1/schema/swagger-ui/")),
    path("api/schema/", lambda r: redirect("/api/v1/schema/")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
