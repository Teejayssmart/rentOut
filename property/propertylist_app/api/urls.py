
app_name = "api"

from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include


from rest_framework.routers import DefaultRouter

from django.views.decorators.cache import cache_page

from propertylist_app.api import views

from .views import EmailOTPVerifyView, EmailOTPResendView


from propertylist_app.api.views import (
    # Rooms & Categories
    RoomAV, RoomDetailAV, RoomListGV, ModerationReportModerateActionView,
    RoomCategorieAV, RoomCategorieDetailAV, RoomCategorieVS,

    # Reviews
    ReviewCreate, ReviewList, ReviewDetail, UserReview,

    # Search & Nearby
    SearchRoomsView, NearbyRoomsView,

    # Saved rooms
    RoomSaveView, RoomSaveToggleView, MySavedRoomsView,

    # Messaging
    MessageThreadListCreateView, MessageListCreateView, ThreadMarkReadView, StartThreadFromRoomView,ThreadMoveToBinView,ThreadRestoreFromBinView,ThreadSetLabelView,
    MessageThreadStateView,MessageStatsView,

    # Bookings & Availability
    create_booking, BookingListCreateView, BookingDetailView, BookingCancelView,
    RoomAvailabilityView, RoomAvailabilitySlotListCreateView, RoomAvailabilitySlotDeleteView, RoomAvailabilityPublicView,  FindAddressView,

    # Photos
    RoomPhotoUploadView, RoomPhotoDeleteView,

    # Auth & Profile
    RegistrationView, LoginView, LogoutView,
    PasswordResetRequestView, PasswordResetConfirmView,
    MeView, UserProfileView,
    UserAvatarUploadView, ChangeEmailView, ChangePasswordView, DeactivateAccountView, MyRoomsView,GoogleRegisterView,AppleRegisterView,

    # Soft delete
    RoomSoftDeleteView,

    # Payments
    CreateListingCheckoutSessionView, stripe_webhook, StripeSuccessView, StripeCancelView,

    # Webhooks
    webhook_in, ProviderWebhookView,

    # Reports / Moderation / Ops
    ReportCreateView, ModerationReportListView, ModerationReportUpdateView,
    RoomModerationStatusView, OpsStatsView,
    
    # --- GDPR / Privacy ---
    DataExportStartView, DataExportLatestView, AccountDeletePreviewView, AccountDeleteConfirmView,
    
    # Notifications
    NotificationListView, NotificationMarkReadView, NotificationMarkAllReadView,
    
    
    HealthCheckView,
    
   
   
)



router = DefaultRouter()
router.register("category", RoomCategorieVS, basename="roomcategory")  # DRF ViewSet routes

urlpatterns = [
    
    # --- Rooms ---
    path("rooms/",                     RoomAV.as_view(),            name="room-list"),
    path("rooms/<int:pk>/",            RoomDetailAV.as_view(),      name="room-detail"),
    
    # Cached alt list
    path("rooms-alt/",                 cache_page(60)(RoomListGV.as_view()),  name="room-list-alt"),
    path("", include(router.urls)),

    # Room categories
    path("room-categories/",           RoomCategorieAV.as_view(),         name="roomcategory-list"),
    path("room-categories/<int:pk>/",  RoomCategorieDetailAV.as_view(),   name="roomcategory-detail"),

    # --- Reviews ---
    path("rooms/<int:pk>/reviews/",        ReviewList.as_view(),       name="room-reviews"),
    path("rooms/<int:pk>/reviews/create/", ReviewCreate.as_view(),     name="room-reviews-create"),
    path("reviews/<int:pk>/",              ReviewDetail.as_view(),     name="review-detail"),
    path("user-reviews/",                  UserReview.as_view(),       name="user-reviews"),

    # --- Search & discovery ---
    path("search/rooms/",  cache_page(60)(SearchRoomsView.as_view()),  name="search-rooms"),
    path("rooms/nearby/",  NearbyRoomsView.as_view(),                  name="rooms-nearby"),

    # --- Saved rooms ---
    path("rooms/<int:pk>/save/",           RoomSaveView.as_view(),       name="room-save"),
    path("rooms/<int:pk>/save-toggle/",    RoomSaveToggleView.as_view(), name="room-save-toggle"),
    path("users/me/saved/rooms/",          MySavedRoomsView.as_view(),   name="my-saved-rooms"),

    # --- Messaging ---
    path("messages/threads/",                              MessageThreadListCreateView.as_view(), name="message-threads"),
    path("messages/threads/<int:thread_id>/messages/",     MessageListCreateView.as_view(),       name="thread-messages"),
    path("messages/threads/<int:thread_id>/read/",         ThreadMarkReadView.as_view(),          name="thread-mark-read"),
    path("rooms/<int:room_id>/start-thread/",              StartThreadFromRoomView.as_view(),     name="start-thread-from-room"),

    # Bin (per-user)
    path("messages/threads/<int:thread_id>/bin/",          ThreadMoveToBinView.as_view(),         name="message-thread-bin"),
    path("messages/threads/<int:thread_id>/restore/",      ThreadRestoreFromBinView.as_view(),     name="message-thread-restore"),

    # Set label (Good Fit, Viewing Scheduled, etc.)
    path("messages/threads/<int:thread_id>/label/",        ThreadSetLabelView.as_view(),           name="message-thread-label"),

    # Full per-user thread state update (label + bin)
    path("messages/threads/<int:thread_id>/state/",        MessageThreadStateView.as_view(),       name="thread-state"),

    #Message statistics (for homepage quick filters)
    path("messages/stats/",                                MessageStatsView.as_view(),             name="messages-stats"),




    # --- Bookings / viewings ---
    path("bookings/create/",               create_booking,                  name="booking-create"),
    path("bookings/",                      BookingListCreateView.as_view(), name="bookings-list-create"),
    path("bookings/<int:pk>/",             BookingDetailView.as_view(),     name="booking-detail"),
    path("bookings/<int:pk>/cancel/",      BookingCancelView.as_view(),     name="booking-cancel"),
    path("rooms/<int:pk>/availability/",   RoomAvailabilityView.as_view(),  name="room-availability"),

    # Landlord manage slots
    path("rooms/<int:pk>/availability/slots/",               RoomAvailabilitySlotListCreateView.as_view(), name="room-slots"),
    path("rooms/<int:pk>/availability/slots/<int:slot_id>/", RoomAvailabilitySlotDeleteView.as_view(),     name="room-slots-delete"),

    # Public view of slots
    path("rooms/<int:pk>/availability/slots/public/",        RoomAvailabilityPublicView.as_view(),         name="room-slots-public"),

    # --- Photos ---
    path("rooms/<int:pk>/photos/",                RoomPhotoUploadView.as_view(), name="room-photo-upload"),
    path("rooms/<int:pk>/photos/<int:photo_id>/", RoomPhotoDeleteView.as_view(), name="room-photo-delete"),

    # --- User / Profile ---
    path("users/me/",                 MeView.as_view(),               name="user-me"),
    path("users/me/profile/",         UserProfileView.as_view(),      name="user-profile"),
    path("users/me/profile/avatar/",  UserAvatarUploadView.as_view(), name="user-avatar-upload"),
    path("users/me/change-email/",    ChangeEmailView.as_view(),      name="user-change-email"),
    path("users/me/change-password/", ChangePasswordView.as_view(),   name="user-change-password"),
    path("users/me/deactivate/",      DeactivateAccountView.as_view(), name="user-deactivate"),

    # --- Soft delete room ---
    path("rooms/<int:pk>/soft-delete/", RoomSoftDeleteView.as_view(), name="room-soft-delete"),

        # --- Auth ---
    path("auth/register/",               RegistrationView.as_view(),         name="auth-register"),
    path("auth/login/",                  LoginView.as_view(),                name="auth-login"),
    path("auth/logout/",                 LogoutView.as_view(),               name="auth-logout"),
    path("auth/password-reset/",         PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("auth/password-reset/confirm/", PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),

    # Social sign-up stubs (for Figma buttons)           # NEW
    path("auth/register/google/",        GoogleRegisterView.as_view(),       name="auth-register-google"),  # NEW
    path("auth/register/apple/",         AppleRegisterView.as_view(),        name="auth-register-apple"),   # NEW


    # --- Payments (Stripe) ---
    path("payments/checkout/rooms/<int:pk>/", CreateListingCheckoutSessionView.as_view(), name="payments-checkout-room"),
    path("payments/webhook/",                 stripe_webhook,                         name="stripe-webhook"),
    path("payments/success/",                 StripeSuccessView.as_view(),            name="payments-success"),
    path("payments/cancel/",                  StripeCancelView.as_view(),             name="payments-cancel"),

    # --- Webhooks ---
    path("webhooks/incoming/",                webhook_in,                    name="webhook-incoming"),
    path("webhooks/<str:provider>/incoming/", ProviderWebhookView.as_view(), name="provider-webhook"),

    # --- Reports / Moderation / Ops ---
    path("reports/",                         ReportCreateView.as_view(),          name="report-create"),
    path("moderation/reports/",              ModerationReportListView.as_view(),  name="moderation-report-list"),
    path("moderation/reports/<int:pk>/",     ModerationReportUpdateView.as_view(), name="moderation-report-update"),
    path("moderation/rooms/<int:pk>/status/", RoomModerationStatusView.as_view(),  name="moderation-room-status"),
    path("reports/<int:pk>/moderate/",     ModerationReportModerateActionView.as_view(), name="report-moderate"),

    path("ops/stats/",                       OpsStatsView.as_view(),               name="ops-stats"),

    # --- Privacy / GDPR ---
    path("users/me/export/",         DataExportStartView.as_view(),     name="me-export-start"),
    path("users/me/export/latest/",  DataExportLatestView.as_view(),    name="me-export-latest"),
    path("users/me/delete/preview/", AccountDeletePreviewView.as_view(), name="me-delete-preview"),
    path("users/me/delete/confirm/", AccountDeleteConfirmView.as_view(), name="me-delete-confirm"),

    # --- Notifications ---
    path("notifications/",               NotificationListView.as_view(),        name="notifications-list"),
    path("notifications/<int:pk>/read/", NotificationMarkReadView.as_view(),    name="notification-mark-read"),
    path("notifications/read/all/",      NotificationMarkAllReadView.as_view(), name="notifications-mark-all-read"),
    
    
    path("health/", HealthCheckView.as_view(), name="health"),
    
    path("auth/verify-otp/", EmailOTPVerifyView.as_view(), name="auth-verify-otp"),
    path("auth/resend-otp/", EmailOTPResendView.as_view(), name="auth-resend-otp"),

    
    # Home page summary + city list
    path("home/", views.HomePageView.as_view(), name="api-home"),
    path("cities/", views.CityListView.as_view(), name="api-city-list"),
    path("rooms/mine/", MyRoomsView.as_view(), name="rooms-mine"),



    # --- Search & discovery ---
    path("search/rooms/",  cache_page(60)(SearchRoomsView.as_view()),  name="search-rooms"),
    path("rooms/nearby/",  NearbyRoomsView.as_view(),                  name="rooms-nearby"),
    path("search/find-address/", FindAddressView.as_view(),            name="search-find-address"),


]

    
    
   


# Serve media in development only
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
