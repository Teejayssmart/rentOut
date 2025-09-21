from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework import status
from rest_framework.views import APIView
from rest_framework import generics
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle, ScopedRateThrottle
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import transaction
from ..models import IdempotencyKey
from ..validators import ensure_idempotency
from django.contrib.auth import authenticate
from rest_framework.decorators import api_view  # needed for create_booking view
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import generics, permissions
from rest_framework.parsers import MultiPartParser, FormParser
from datetime import datetime  # to parse incoming datetimes
from ..models import Booking    # booking model used below
from ..models import RoomImage
from ..validators import validate_no_booking_conflict
from ..models import WebhookReceipt
from ..validators import verify_webhook_signature, ensure_webhook_not_replayed

from propertylist_app.api.permissions import IsAdminOrReadOnly, IsReviewUserOrReadOnly
from propertylist_app.models import Room, RoomCategorie, Review
from propertylist_app.api.serializers import RoomSerializer, RoomCategorieSerializer, ReviewSerializer
from propertylist_app.api.throttling import ReviewCreateThrottle, ReviewListThrottle
from propertylist_app.api.pagination import RoomPagination, RoomLOPagination, RoomCPagination
from .serializers import (
    RegistrationSerializer, LoginSerializer,
    PasswordResetRequestSerializer, PasswordResetConfirmSerializer,
    UserSerializer, UserProfileSerializer,  SearchFiltersSerializer
)




class UserReview(generics.ListAPIView):
    serializer_class = ReviewSerializer

    def get_queryset(self):
        username = self.request.query_params.get('username', None)
        return Review.objects.filter(review_user__username=username)


class ReviewCreate(generics.CreateAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReviewCreateThrottle]

    def get_queryset(self):
        return Review.objects.all()

    def perform_create(self, serializer):
        pk = self.kwargs.get('pk')
        room = Room.objects.get(pk=pk)

        review_user = self.request.user
        review_queryset = Review.objects.filter(room=room, review_user=review_user)

        if review_queryset.exists():
            raise ValidationError("You have already reviewed this room!")

        # correct average rating calculation
        new_rating = serializer.validated_data['rating']
        if room.number_rating == 0:
            room.avg_rating = new_rating
        else:
            room.avg_rating = ((room.avg_rating * room.number_rating) + new_rating) / (room.number_rating + 1)

        room.number_rating = room.number_rating + 1
        room.save()

        serializer.save(room=room, review_user=review_user)


class ReviewList(generics.ListAPIView):
    serializer_class = ReviewSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['review_user__username', 'active']

    def get_queryset(self):
        pk = self.kwargs['pk']
        return Review.objects.filter(room=pk)


class ReviewDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer
    permission_classes = [IsReviewUserOrReadOnly]
    throttle_classes = [ScopedRateThrottle, AnonRateThrottle]
    throttle_scope = 'review-detail'


class RoomCategorieVS(viewsets.ModelViewSet):
    queryset = RoomCategorie.objects.all()
    serializer_class = RoomCategorieSerializer
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]  # fixed typo


class RoomCategorieAV(APIView):
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]

    def get(self, request):
        categories = RoomCategorie.objects.all()
        serializer = RoomCategorieSerializer(categories, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = RoomCategorieSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)  # add 400


class RoomCategorieDetailAV(APIView):
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]

    def get(self, request, pk):
        try:
            category = RoomCategorie.objects.get(pk=pk)
        except RoomCategorie.DoesNotExist:
            return Response({'error': 'Property not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = RoomCategorieSerializer(category)
        return Response(serializer.data)

    def put(self, request, pk):
        category = RoomCategorie.objects.get(pk=pk)
        serializer = RoomCategorieSerializer(category, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        category = RoomCategorie.objects.get(pk=pk)
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoomListGV(generics.ListAPIView):
    queryset = Room.objects.alive()
    serializer_class = RoomSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['avg_rating', 'category__name']
    pagination_class = RoomLOPagination  # keep one; the last one was effective


class RoomAV(APIView):
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]

    def get(self, request):
        rooms = Room.objects.alive()
        serializer = RoomSerializer(rooms, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = RoomSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(property_owner=request.user)
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)  # add 400

class RoomDetailAV(APIView):
    permission_classes = [IsAdminOrReadOnly]

    def get(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        serializer = RoomSerializer(room)
        return Response(serializer.data)

    def put(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        serializer = RoomSerializer(room, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        serializer = RoomSerializer(room, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        room.soft_delete()  # ← soft delete instead of hard delete
        return Response(status=status.HTTP_204_NO_CONTENT)



@transaction.atomic
@api_view(["POST"])
def create_booking(request):
    key = request.headers.get("Idempotency-Key")
    info = ensure_idempotency(
        user_id=request.user.id,
        key=key,
        action="create_booking",
        payload_bytes=request.body,
        idem_qs=IdempotencyKey.objects
    )

    room_id = request.data.get("room")
    start_str = request.data.get("start")
    end_str = request.data.get("end")
    if not room_id or not start_str or not end_str:
        return Response(
            {"detail": "room, start, and end are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    room = get_object_or_404(Room, pk=room_id)

    try:
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
    except Exception:
        return Response(
            {"detail": "start and end must be ISO 8601 datetimes."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    Booking.objects.select_for_update().filter(room=room)
    validate_no_booking_conflict(room, start_dt, end_dt, Booking.objects)

    IdempotencyKey.objects.create(
        user_id=request.user.id,
        key=key,
        action="create_booking",
        request_hash=info["request_hash"]
    )

    return Response({"detail": "Validated. Ready to create booking."}, status=status.HTTP_200_OK)


@api_view(["POST"])
def webhook_in(request):
    sig_header = request.headers.get("X-Signature", "")
    verify_webhook_signature(
        secret="YOUR_WEBHOOK_SECRET",
        payload=request.body,
        signature_header=sig_header,
        scheme="sha256=",
        clock_skew=300
    )

    event_id = request.headers.get("X-Event-Id") or request.data.get("id")
    ensure_webhook_not_replayed(event_id, WebhookReceipt.objects)

    WebhookReceipt.objects.create(source="provider", event_id=event_id)
    return Response({"ok": True}, status=status.HTTP_200_OK)



# Registration
class RegistrationView(generics.CreateAPIView):
    serializer_class = RegistrationSerializer
    permission_classes = [permissions.AllowAny]


# Login
class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]

        user = authenticate(request, username=username, password=password)
        if not user:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_400_BAD_REQUEST)

        refresh = RefreshToken.for_user(user)
        return Response(
            {"refresh": str(refresh), "access": str(refresh.access_token)},
            status=status.HTTP_200_OK,
        )

        
     


# Logout
class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response({"detail": "Refresh token required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except Exception:
            return Response({"detail": "Invalid or expired refresh token."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Logged out."}, status=status.HTTP_200_OK)


# Password reset request
class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"detail": "Password reset email would be sent"})


# Password reset confirm
class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"detail": "Password has been reset"})


# Current user info
class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


# Current user profile
class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user.profile
    
    

class RoomPhotoUploadView(APIView):
    permission_classes = [IsAuthenticated]
    # This tells DRF that the request will come as multipart/form-data (the standard for file uploads).
    parser_classes = [MultiPartParser, FormParser]
        # Look up the Room by primary key (pk) in the URL.
        # Also check that the property_owner is the logged-in user.
        # If not found → 404 error.
    def post(self, request, pk):
        room = get_object_or_404(Room, pk=pk, property_owner=request.user)
        file_obj = request.FILES.get("image")
        if not file_obj:
            return Response({"detail": "image file is required (form-data key 'image')."},
                            status=status.HTTP_400_BAD_REQUEST)
            # Saves the file to MEDIA_ROOT/room_images/ (because of upload_to='room_images/').
        photo = RoomImage.objects.create(room=room, image=file_obj)
        return Response({"id": photo.id, "image": photo.image.url}, status=status.HTTP_201_CREATED)

class RoomPhotoDeleteView(APIView):
    permission_classes = [IsAuthenticated]
       
    def delete(self, request, pk, photo_id):
        room = get_object_or_404(Room, pk=pk, property_owner=request.user)
        photo = get_object_or_404(RoomImage, pk=photo_id, room=room)
        photo.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
class MyRoomsView(generics.ListAPIView):
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Room.objects.alive().filter(property_owner=self.request.user)
    
    
class SearchRoomsView(generics.ListAPIView):
    """
    GET /api/search/rooms/?q=&min_price=&max_price=&postcode=&radius_km=&ordering=
    Uses your existing SearchFiltersSerializer to validate query params.
    """
    serializer_class = RoomSerializer  # for results
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        # validate query params
        filters_ser = SearchFiltersSerializer(data=self.request.query_params)
        filters_ser.is_valid(raise_exception=True)
        data = filters_ser.validated_data

        qs = Room.objects.alive()

        # free text: title / description / location
        q = data.get("q")
        if q:
            qs = qs.filter(
                models.Q(title__icontains=q) |
                models.Q(description__icontains=q) |
                models.Q(location__icontains=q)
            )

        # price range
        min_price = data.get("min_price")
        if min_price is not None:
            qs = qs.filter(price_per_month__gte=min_price)

        max_price = data.get("max_price")
        if max_price is not None:
            qs = qs.filter(price_per_month__lte=max_price)

        # postcode (normalized by the serializer if provided)
        postcode = data.get("postcode")
        if postcode:
            # simple heuristic: many sites keep the postcode at the end of location
            qs = qs.filter(location__iendswith=postcode)

        # NOTE: radius_km is validated already; without geospatial data we don’t compute distances here.

        # ordering (already validated/whitelisted by the serializer)
        ordering = data.get("ordering")
        if ordering:
            qs = qs.order_by(*[p.strip() for p in ordering.split(",") if p.strip()])

        return qs


class NearbyRoomsView(generics.ListAPIView):
    """
    GET /api/rooms/nearby/?postcode=&radius_km=
    Minimal 'nearby' using postcode suffix match; radius is accepted but not used for distance.
    """
    serializer_class = RoomSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        # Re-use the same serializer to validate postcode/radius
        ser = SearchFiltersSerializer(data=self.request.query_params)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        postcode = data.get("postcode")
        # SearchFiltersSerializer already enforces postcode if radius_km is provided
        if not postcode:
            # If no postcode, return empty queryset (or raise 400 in a custom way)
            return Room.objects.none()

        qs = Room.objects.alive().filter(location__iendswith=postcode)
        return qs
    
