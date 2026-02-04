from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from django.http import JsonResponse
from django.conf import settings as dj_settings
import importlib


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



from django.http import JsonResponse
from django.conf import settings as dj_settings
from django.urls import get_resolver, reverse
import importlib


from django.http import JsonResponse
from django.conf import settings as dj_settings
from django.urls import get_resolver, reverse
import importlib


def debug_urls(request):
    module_name = dj_settings.ROOT_URLCONF
    mod = importlib.import_module(module_name)

    resolver = get_resolver()
    all_patterns = []

    # collect flat list of pattern strings that Django knows about
    for p in resolver.url_patterns:
        try:
            all_patterns.append(str(p.pattern))
        except Exception:
            all_patterns.append(repr(p))

    # check if swagger-ui route name can be reversed
    try:
        swagger_ui_url = reverse("swagger-ui")
    except Exception as e:
        swagger_ui_url = f"reverse_failed: {type(e).__name__}: {e}"

    # check if schema route name can be reversed
    try:
        schema_url = reverse("schema")
    except Exception as e:
        schema_url = f"reverse_failed: {type(e).__name__}: {e}"

    return JsonResponse(
        {
            "ROOT_URLCONF": module_name,
            "URLCONF_FILE": getattr(mod, "__file__", None),
            "DEBUG": dj_settings.DEBUG,
            "reverse_schema": schema_url,
            "reverse_swagger_ui": swagger_ui_url,
            "top_level_patterns": all_patterns,
        }
    )






urlpatterns = [
    
    path("debug/urls/", debug_urls),  
    path("admin/", admin.site.urls),
    path("api/v1/",include(("propertylist_app.api.urls", "api"), namespace="v1"),),

    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/",SpectacularSwaggerView.as_view(url_name="schema"),name="swagger-ui",),
    path("api/schema/redoc/",SpectacularRedocView.as_view(url_name="schema"),name="redoc",),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
