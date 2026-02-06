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

    # TEMP: troubleshooting (remove later)
    path("debug/urls/", debug_urls),

    # JWT token endpoints (NOT versioned)
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    # ✅ Versioned API (this MUST capture `version` for URLPathVersioning)
    re_path(
        r"^api/(?P<version>v1|v2)/",
        include("propertylist_app.api.urls"),
    ),

    # ✅ Versioned schema endpoints (also capture `version`)
    re_path(r"^api/(?P<version>v1|v2)/schema/$", SpectacularAPIView.as_view(), name="schema"),
    re_path(
        r"^api/(?P<version>v1|v2)/schema/swagger-ui/$",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    re_path(
        r"^api/(?P<version>v1|v2)/schema/redoc/$",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),

    # Redirect old (unversioned) schema links to v1
    path("api/schema/", lambda r: redirect("/api/v1/schema/")),
    path("api/schema/swagger-ui/", lambda r: redirect("/api/v1/schema/swagger-ui/")),
    path("api/schema/redoc/", lambda r: redirect("/api/v1/schema/redoc/")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
