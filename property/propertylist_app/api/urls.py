from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

from rest_framework.routers import DefaultRouter

from propertylist_app.api.views import (
    RoomAV,
    RoomDetailAV,
    RoomCategorieAV,
    RoomCategorieDetailAV,
    ReviewCreate,
    ReviewList,
    ReviewDetail,
    RoomCategorieVS,
    UserReview,
    RoomListGV,
    create_booking,
    webhook_in,
    RegistrationView,
    LoginView,
    LogoutView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    MeView,
    UserProfileView,
    RoomPhotoUploadView,
    RoomPhotoDeleteView,
    MyRoomsView,
    SearchRoomsView,
    NearbyRoomsView,
    RoomSaveView,
    MySavedRoomsView,
    MessageThreadListCreateView,
    MessageListCreateView,
)




router = DefaultRouter()
router.register('category', RoomCategorieVS, basename='roomcategory')

urlpatterns = [
    # Rooms
    path('rooms/', RoomAV.as_view(), name='room-list'),
    path('rooms/<int:pk>/', RoomDetailAV.as_view(), name='room-detail'),
    
     # Alternate rooms list with ordering/pagination
    path('rooms-alt/', RoomListGV.as_view(), name='room-list-alt'),
    path('',include(router.urls)),
    
    # Room categories
    path('room-categories/', RoomCategorieAV.as_view(), name='roomcategory-list'),
    path('room-categories/<int:pk>/', RoomCategorieDetailAV.as_view(), name='roomcategory-detail'),

    
    # Reviews
    path('rooms/<int:pk>/reviews/', ReviewList.as_view(), name='room-reviews'),
    path('rooms/<int:pk>/reviews/create/', ReviewCreate.as_view(), name='room-reviews-create'),
    path('reviews/<int:pk>/', ReviewDetail.as_view(), name='review-detail'),
    path('user-reviews/', UserReview.as_view(), name='user-reviews'),

    
     path('reviews/<str:username>/', UserReview.as_view(), name='user-review-detail'),
     
     # Booking
    path('bookings/create/', create_booking, name='booking-create'),

    # Webhooks
    path('webhooks/incoming/', webhook_in, name='webhook-incoming'),
    
    # Auth
    path("auth/register/", RegistrationView.as_view(), name="auth-register"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/password-reset/", PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("auth/password-reset/confirm/", PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),

    # User
    path("users/me/", MeView.as_view(), name="user-me"),
    path("users/me/profile/", UserProfileView.as_view(), name="user-profile"),
    
 
    
    

    path('rooms/<int:pk>/photos/', RoomPhotoUploadView.as_view(), name='room-photo-upload'),
    path('rooms/<int:pk>/photos/<int:photo_id>/', RoomPhotoDeleteView.as_view(), name='room-photo-delete'),
    
    path('users/me/rooms/', MyRoomsView.as_view(), name='my-rooms'),
    
    # Search & discovery
    path('search/rooms/', SearchRoomsView.as_view(), name='search-rooms'),      # ← GET /api/search/rooms/
    path('rooms/nearby/', NearbyRoomsView.as_view(), name='rooms-nearby'),      # ← GET /api/rooms/nearby/

    path('rooms/<int:pk>/save/', RoomSaveView.as_view(), name='room-save'),
    path('users/me/saved/rooms/', MySavedRoomsView.as_view(), name='my-saved-rooms'),
    
    path("messages/threads/", MessageThreadListCreateView.as_view(), name="message-threads"),
    path("messages/threads/<int:thread_id>/messages/", MessageListCreateView.as_view(), name="thread-messages"), 

    
]

