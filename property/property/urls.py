from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.shortcuts import redirect

import os

from django.urls import re_path
from django.views.static import serve


from propertylist_app.api.views import LoginView

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

    # DEBUG helper
    path("debug-urls/", debug_urls),

    # API includes (ONLY ONCE EACH)
    path("api/", include(("propertylist_app.api.urls", "api"), namespace="api")),
    path("api/v1/", include(("propertylist_app.api.urls", "v1"), namespace="v1")),

    # JWT token endpoints (NOT versioned)
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    # Required by tests (unversioned)
    path("api/auth/login/", LoginView.as_view(), name="auth-login"),

    # Schema endpoints
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),

    # Redirect old schema URLs
    path("api/schema/", lambda r: redirect("/api/v1/schema/")),
    path("api/schema/swagger-ui/", lambda r: redirect("/api/v1/schema/swagger-ui/")),
    path("api/schema/redoc/", lambda r: redirect("/api/v1/schema/redoc/")),
]



# Serve uploaded media:
# - DEBUG=True (local dev)
# - OR staging when SERVE_MEDIA=1 (Render disk)
SERVE_MEDIA = os.getenv("SERVE_MEDIA", "").lower() in {"1", "true", "yes"}

if settings.DEBUG or SERVE_MEDIA:
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]

