
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# JWT views
from rest_framework_simplejwt.views import (
    TokenObtainPairView,   # POST /api/auth/token/
    TokenRefreshView,      # POST /api/auth/token/refresh/
    TokenVerifyView,       # POST /api/auth/token/verify/ (optional)
)



urlpatterns = [
    path("admin/", admin.site.urls),

    # Your main API (rooms, reviews, bookings, etc.)
    path("api/", include("propertylist_app.api.urls")),

    # ✅ JWT-only auth routes
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    # (Optional) If you’ve created custom views for register/me/logout/password reset, expose them here:
    # path("api/auth/register/", RegistrationView.as_view(), name="auth_register"),
    # path("api/auth/me/", MeView.as_view(), name="auth_me"),
    # path("api/auth/logout/", LogoutView.as_view(), name="auth_logout"),
    # path("api/auth/password-reset/", PasswordResetRequestView.as_view(), name="password_reset_request"),
    # path("api/auth/password-reset/confirm/", PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    