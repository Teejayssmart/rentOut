from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# JWT views
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

# property/property/urls.py  (ONLY the include lines changed)

urlpatterns = [
    path("admin/", admin.site.urls),

    # 1) Plain include with NO namespace (so tests can reverse simple names)
    #    The ", None" prevents Django from auto-using app_name as a namespace.
    path("api/", include(("propertylist_app.api.urls", None))),

    # 2) Explicit namespace "api" at the same base path
    path("api/", include(("propertylist_app.api.urls", "api"), namespace="api")),

    # 3) Versioned include with its own unique namespace
    path("api/v1/", include(("propertylist_app.api.urls", "api"), namespace="v1")),

    # JWT-only auth routes
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    # OpenAPI schema + UIs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
