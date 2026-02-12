from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.shortcuts import redirect

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
    
    
    # existing v1
    path("api/v1/", include(("propertylist_app.api.urls", "v1"), namespace="v1")),
    path("api/", include(("propertylist_app.api.urls", "api"), namespace="api")),


    

    # JWT token endpoints (NOT versioned)
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    #  REQUIRED by tests (unversioned)
    path("api/auth/login/", LoginView.as_view(), name="auth-login"),

    # v1 API (namespaced)
    path("api/v1/", include(("propertylist_app.api.urls", "v1"), namespace="v1")),

    # v1 schema endpoints
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/v1/schema/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),

    # Redirect old schema URLs
    path("api/schema/", lambda r: redirect("/api/v1/schema/")),
    path("api/schema/swagger-ui/", lambda r: redirect("/api/v1/schema/swagger-ui/")),
    path("api/schema/redoc/", lambda r: redirect("/api/v1/schema/redoc/")),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
