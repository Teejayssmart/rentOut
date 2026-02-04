from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from django.http import JsonResponse
from django.conf import settings as dj_settings
import importlib


def debug_urls(request):
    module_name = dj_settings.ROOT_URLCONF
    mod = importlib.import_module(module_name)
    return JsonResponse(
        {
            "ROOT_URLCONF": module_name,
            "URLCONF_FILE": getattr(mod, "__file__", None),
            "DEBUG": dj_settings.DEBUG,
        }
    )




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

urlpatterns = [
    
    path("debug/urls/", debug_urls),

    
    path("admin/", admin.site.urls),

    path(
        "api/v1/",
        include(("propertylist_app.api.urls", "api"), namespace="v1"),
    ),

    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/",SpectacularSwaggerView.as_view(url_name="schema"),name="swagger-ui",),
    path("api/schema/redoc/",SpectacularRedocView.as_view(url_name="schema"),name="redoc",),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
