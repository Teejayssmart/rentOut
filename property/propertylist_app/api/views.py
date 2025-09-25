from datetime import datetime

from django.contrib.auth import authenticate
from django.contrib.auth.models import User   # ✅ Added
from django.db import transaction
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import (
    generics,
    permissions,
    status,
    filters,
    viewsets,
    serializers,   # ✅ Added for EmailField validation
)
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.throttling import (
    UserRateThrottle,
    AnonRateThrottle,
    ScopedRateThrottle,
)
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

# Models
from propertylist_app.models import (
    Room,
    RoomCategorie,
    Review,
    SavedRoom,
    MessageThread,
    Message,
    AvailabilitySlot,
    Booking,
    RoomImage,
    WebhookReceipt,
    IdempotencyKey,
)

# Validators / helpers
from propertylist_app.validators import (
    ensure_idempotency,
    validate_no_booking_conflict,
    verify_webhook_signature,
    ensure_webhook_not_replayed,
    geocode_postcode,
    haversine_miles,
    validate_radius_miles,
    normalize_uk_postcode,
    validate_avatar_image,   # ✅ Added for avatar upload
)

from propertylist_app.api.pagination import RoomPagination, RoomLOPagination, RoomCPagination
from propertylist_app.api.permissions import (
    IsAdminOrReadOnly,
    IsReviewUserOrReadOnly,
    IsOwnerOrReadOnly,
)
from propertylist_app.api.serializers import (
    RoomSerializer,
    RoomCategorieSerializer,
    ReviewSerializer,
    RoomImageSerializer,
    MessageThreadSerializer,
    MessageSerializer,
    BookingSerializer,
    AvailabilitySlotSerializer,
)
from propertylist_app.api.throttling import ReviewCreateThrottle, ReviewListThrottle

from .serializers import (
    RegistrationSerializer,
    LoginSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    UserSerializer,
    UserProfileSerializer,
    SearchFiltersSerializer,
)


# --------------------
# Reviews
# --------------------
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
    


class RoomCategorieAV(APIView):
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]

    def get(self, request):
        qs = RoomCategorie.objects.all().order_by("name")
        # Non-staff users see only active categories
        if not (request.user and request.user.is_staff):
            qs = qs.filter(active=True)
        serializer = RoomCategorieSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = RoomCategorieSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
s




# --------------------
# Categories
# --------------------
class RoomCategorieVS(viewsets.ModelViewSet):
    serializer_class = RoomCategorieSerializer
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]

    def get_queryset(self):
        qs = RoomCategorie.objects.all().order_by("name")
        user = getattr(self.request, "user", None)
        if not (user and user.is_staff):
            qs = qs.filter(active=True)
        return qs


class RoomCategorieAV(APIView):
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]

    def get(self, request):
        qs = RoomCategorie.objects.all().order_by("name")
        if not (request.user and request.user.is_staff):
            qs = qs.filter(active=True)
        serializer = RoomCategorieSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = RoomCategorieSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RoomCategorieDetailAV(APIView):
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]

    def get(self, request, pk):
        category = get_object_or_404(RoomCategorie, pk=pk)
        serializer = RoomCategorieSerializer(category)
        return Response(serializer.data)

    def put(self, request, pk):
        category = get_object_or_404(RoomCategorie, pk=pk)
        serializer = RoomCategorieSerializer(category, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        category = get_object_or_404(RoomCategorie, pk=pk)
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)



# --------------------
# Rooms
# --------------------
class RoomListGV(generics.ListAPIView):
    queryset = Room.objects.alive()
    serializer_class = RoomSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['avg_rating', 'category__name']
    pagination_class = RoomLOPagination


class RoomAV(APIView):
    throttle_classes = [AnonRateThrottle]
    permission_classes = [IsAuthenticatedOrReadOnly]

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
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RoomDetailAV(APIView):
    # Read for everyone; modify only owner/staff
    permission_classes = [IsOwnerOrReadOnly]

    def get(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        serializer = RoomSerializer(room)
        return Response(serializer.data)

    def put(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        serializer = RoomSerializer(room, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        serializer = RoomSerializer(room, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        room.soft_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class RoomSoftDeleteView(APIView):
    """
    POST /api/rooms/<id>/soft-delete/
    """
    permission_classes = [IsOwnerOrReadOnly]

    def post(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        room.soft_delete()
        return Response({"detail": f"Room {room.id} soft-deleted."}, status=status.HTTP_200_OK)

# --------------------
# Idempotent booking validation endpoint (legacy)
# --------------------
@transaction.atomic
@api_view(["POST"])
@permission_classes([IsAuthenticated])
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


# --------------------
# Webhooks
# --------------------
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


# --------------------
# Auth / Profile
# --------------------
class RegistrationView(generics.CreateAPIView):
    serializer_class = RegistrationSerializer
    permission_classes = [permissions.AllowAny]


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


class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"detail": "Password reset email would be sent"})


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"detail": "Password has been reset"})


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user.profile


# --------------------
# Room photos
# --------------------
class RoomPhotoUploadView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    serializer_class = RoomImageSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_room(self):
        room = get_object_or_404(Room, pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, room)
        return room

    def perform_create(self, serializer):
        room = self.get_room()
        file_obj = self.request.FILES.get("image")
        if not file_obj:
            raise ValidationError({"image": "image file is required (form-data key 'image')."})
        serializer.save(room=room, image=file_obj)


class RoomPhotoDeleteView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    serializer_class = RoomImageSerializer
    queryset = RoomImage.objects.select_related("room")
    lookup_url_kwarg = "photo_id"

    def get_object(self):
        obj = super().get_object()
        self.check_object_permissions(self.request, obj.room)
        return obj


# --------------------
# My Rooms / Search / Nearby
# --------------------
class MyRoomsView(generics.ListAPIView):
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Room.objects.alive().filter(property_owner=self.request.user)


class SearchRoomsView(generics.ListAPIView):
    """
    GET /api/search/rooms/?q=&min_price=&max_price=&postcode=&radius_km=&ordering=
    """
    serializer_class = RoomSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        filters_ser = SearchFiltersSerializer(data=self.request.query_params)
        filters_ser.is_valid(raise_exception=True)
        data = filters_ser.validated_data

        qs = Room.objects.alive()

        q = data.get("q")
        if q:
            qs = qs.filter(
                Q(title__icontains=q) |
                Q(description__icontains=q) |
                Q(location__icontains=q)
            )

        min_price = data.get("min_price")
        if min_price is not None:
            qs = qs.filter(price_per_month__gte=min_price)

        max_price = data.get("max_price")
        if max_price is not None:
            qs = qs.filter(price_per_month__lte=max_price)

        postcode = data.get("postcode")
        if postcode:
            qs = qs.filter(location__iendswith=postcode)

        ordering = data.get("ordering")
        if ordering:
            qs = qs.order_by(*[p.strip() for p in ordering.split(",") if p.strip()])

        return qs


class NearbyRoomsView(generics.ListAPIView):
    serializer_class = RoomSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = RoomLOPagination

    _ordered_ids = None
    _distance_by_id = None

    def get_queryset(self):
        postcode_raw = (self.request.query_params.get("postcode") or "").strip()
        if not postcode_raw:
            raise ValidationError({"postcode": "Postcode is required."})

        postcode = normalize_uk_postcode(postcode_raw)

        raw_radius = self.request.query_params.get("radius_miles", 10)
        radius_miles = validate_radius_miles(raw_radius, max_miles=100)

        lat, lon = geocode_postcode(postcode)

        base_qs = Room.objects.alive().exclude(latitude__isnull=True).exclude(longitude__isnull=True)

        distances = []
        for r in base_qs.only("id", "latitude", "longitude"):
            d = haversine_miles(lat, lon, r.latitude, r.longitude)
            if d <= radius_miles:
                distances.append((r.id, d))

        distances.sort(key=lambda t: t[1])
        self._ordered_ids = [rid for rid, _ in distances]
        self._distance_by_id = {rid: d for rid, d in distances}

        return Room.objects.alive().filter(id__in=self._ordered_ids or [])

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        room_by_id = {obj.id: obj for obj in queryset}
        ordered_objs = []

        for rid in (self._ordered_ids or []):
            obj = room_by_id.get(rid)
            if obj is not None:
                obj.distance_miles = self._distance_by_id.get(rid)
                ordered_objs.append(obj)

        page = self.paginate_queryset(ordered_objs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(ordered_objs, many=True)
        return Response(serializer.data)


# --------------------
# Save / Unsave rooms
# --------------------
class RoomSaveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        SavedRoom.objects.get_or_create(user=request.user, room=room)
        return Response({"saved": True}, status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        SavedRoom.objects.filter(user=request.user, room=room).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MySavedRoomsView(generics.ListAPIView):
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = RoomLOPagination

    def get_queryset(self):
        saved_ids = SavedRoom.objects.filter(user=self.request.user).values_list("room_id", flat=True)
        return (
            Room.objects.alive()
            .filter(id__in=saved_ids)
            .select_related("category")
            .prefetch_related("reviews")
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx


# --------------------
# Messaging
# --------------------
class MessageThreadListCreateView(generics.ListCreateAPIView):
    """
    GET/POST /api/messages/threads/
    """
    serializer_class = MessageThreadSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = RoomLOPagination
    throttle_classes = [UserRateThrottle]

    def get_queryset(self):
        return MessageThread.objects.filter(participants=self.request.user).prefetch_related("participants")

    def perform_create(self, serializer):
        participants = set(serializer.validated_data.get("participants", []))
        participants.add(self.request.user)

        if len(participants) != 2:
            raise ValidationError({"participants": "Threads must have exactly 2 participants (you + one other user)."})

        p_list = list(participants)
        existing = (
            MessageThread.objects
            .filter(participants=p_list[0])
            .filter(participants=p_list[1])
            .annotate(num_participants=Count("participants"))
            .filter(num_participants=2)
        )
        if existing.exists():
            raise ValidationError({"detail": "A thread between you two already exists."})

        thread = serializer.save()
        thread.participants.set(participants)


class MessageListCreateView(generics.ListCreateAPIView):
    """
    GET/POST /api/messages/threads/<thread_id>/messages/
    """
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = RoomLOPagination
    throttle_classes = [UserRateThrottle]

    def get_queryset(self):
        thread_id = self.kwargs["thread_id"]
        return Message.objects.filter(thread__id=thread_id, thread__participants=self.request.user)

    def perform_create(self, serializer):
        thread = get_object_or_404(
            MessageThread.objects.filter(participants=self.request.user),
            id=self.kwargs["thread_id"]
        )
        serializer.save(thread=thread, sender=self.request.user)


# --------------------
# BOOKINGS (viewing requests)
# --------------------
class BookingListCreateView(generics.ListCreateAPIView):
    """
    GET /api/bookings/     → list my bookings
    POST /api/bookings/    → create a booking (slot-based preferred; manual fallback)
    """
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = RoomLOPagination
    throttle_classes = [UserRateThrottle]

    def get_queryset(self):
        return Booking.objects.filter(user=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        # 1) SLOT-BASED BOOKING (preferred if client sends "slot")
        slot_id = self.request.data.get("slot")
        if slot_id:
            slot = get_object_or_404(AvailabilitySlot, pk=slot_id)

            if getattr(slot.room, "is_deleted", False):
                raise ValidationError({"room": "Room is not available."})
            if slot.end <= timezone.now():
                raise ValidationError({"slot": "This slot is in the past."})

            with transaction.atomic():
                slot_locked = AvailabilitySlot.objects.select_for_update().get(pk=slot.pk)
                active = Booking.objects.filter(slot=slot_locked, canceled_at__isnull=True).count()
                if active >= slot_locked.max_bookings:
                    raise ValidationError({"detail": "This slot is fully booked."})

                serializer.save(
                    user=self.request.user,
                    room=slot_locked.room,
                    slot=slot_locked,
                    start=slot_locked.start,
                    end=slot_locked.end,
                )
            return  # important: stop here for slot bookings

        # 2) MANUAL START/END BOOKING (fallback if no "slot" provided)
        room_id = self.request.data.get("room")
        if not room_id:
            raise ValidationError({"room": "This field is required."})
        room = get_object_or_404(Room.objects.alive(), pk=room_id)

        start = serializer.validated_data.get("start")
        end = serializer.validated_data.get("end")
        if not start or not end:
            raise ValidationError({"start": "start and end are required."})
        if start >= end:
            raise ValidationError({"end": "End must be after start."})

        conflicts = Booking.objects.filter(room=room, canceled_at__isnull=True) \
                                   .filter(start__lt=end, end__gt=start) \
                                   .exists()
        if conflicts:
            raise ValidationError({"detail": "Selected dates clash with an existing booking."})

        serializer.save(user=self.request.user, room=room)


class BookingDetailView(generics.RetrieveAPIView):
    """
    GET /api/bookings/<id>/ → see my booking
    """
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return Booking.objects.all()
        return Booking.objects.filter(user=self.request.user)


class BookingCancelView(APIView):
    """
    POST /api/bookings/<id>/cancel/ → soft-cancel a booking (marks canceled_at)
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        qs = Booking.objects.all() if request.user.is_staff else Booking.objects.filter(user=request.user)
        booking = get_object_or_404(qs, pk=pk)

        if booking.canceled_at:
            return Response({"detail": "Booking already cancelled."}, status=status.HTTP_200_OK)

        if booking.start <= timezone.now():
            return Response({"detail": "Cannot cancel after booking has started."},
                            status=status.HTTP_400_BAD_REQUEST)

        booking.canceled_at = timezone.now()
        booking.save(update_fields=["canceled_at"])
        return Response({"detail": "Booking cancelled.", "canceled_at": booking.canceled_at}, status=status.HTTP_200_OK)


# --------------------
# Availability checks & slots
# --------------------
class RoomAvailabilityView(APIView):
    """
    GET /api/rooms/<id>/availability/?from=&to=
    Returns: {"available": bool, "conflicts": [{"id": ..., "start": ..., "end": ...}, ...]}
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        start_str = request.query_params.get("from")
        end_str = request.query_params.get("to")
        if not start_str or not end_str:
            return Response({"detail": "Query params 'from' and 'to' are required (ISO 8601)."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str)
        except Exception:
            return Response({"detail": "from/to must be ISO 8601 datetimes."},
                            status=status.HTTP_400_BAD_REQUEST)
        if start >= end:
            return Response({"detail": "'to' must be after 'from'."},
                            status=status.HTTP_400_BAD_REQUEST)

        conflicts_qs = Booking.objects.filter(room=room, canceled_at__isnull=True) \
                                      .filter(start__lt=end, end__gt=start) \
                                      .values("id", "start", "end") \
                                      .order_by("start")
        conflicts = list(conflicts_qs)
        return Response({"available": len(conflicts) == 0, "conflicts": conflicts}, status=status.HTTP_200_OK)


class RoomAvailabilitySlotListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    serializer_class = AvailabilitySlotSerializer

    def get_room(self):
        room = get_object_or_404(Room.objects.alive(), pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, room)
        return room

    def get_queryset(self):
        room = get_object_or_404(Room.objects.alive(), pk=self.kwargs["pk"])
        return room.availability_slots.order_by("start")

    def perform_create(self, serializer):
        room = self.get_room()
        start = serializer.validated_data.get("start")
        end = serializer.validated_data.get("end")
        if start >= end:
            raise ValidationError({"end": "End must be after start."})
        serializer.save(room=room)


class RoomAvailabilitySlotDeleteView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    serializer_class = AvailabilitySlotSerializer
    lookup_url_kwarg = "slot_id"

    def get_queryset(self):
        return AvailabilitySlot.objects.select_related("room")

    def perform_destroy(self, instance):
        if Booking.objects.filter(slot=instance, canceled_at__isnull=True).exists():
            raise ValidationError({"detail": "Cannot delete a slot with active bookings."})
        self.check_object_permissions(self.request, instance.room)
        return super().perform_destroy(instance)


class RoomAvailabilityPublicView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = AvailabilitySlotSerializer

    def get_queryset(self):
        room = get_object_or_404(Room.objects.alive(), pk=self.kwargs["pk"])
        qs = room.availability_slots.order_by("start")
        f = self.request.query_params.get("from")
        t = self.request.query_params.get("to")
        only_free = self.request.query_params.get("only_free") in {"1", "true", "True"}

        if f and t:
            try:
                start = datetime.fromisoformat(f)
                end = datetime.fromisoformat(t)
            except Exception:
                raise ValidationError({"detail": "from/to must be ISO 8601"})
            qs = qs.filter(start__lt=end, end__gt=start)

        if only_free:
            # Filter in Python to use the property safely
            slot_ids = [s.id for s in qs if Booking.objects.filter(slot=s, canceled_at__isnull=True).count() < s.max_bookings]
            qs = qs.filter(id__in=slot_ids)

        return qs


class UserAvatarUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        profile = request.user.profile
        file_obj = request.FILES.get("avatar")
        if not file_obj:
            return Response({"avatar": "File is required (form-data key 'avatar')."},
                            status=status.HTTP_400_BAD_REQUEST)
        cleaned = validate_avatar_image(file_obj)
        profile.avatar = cleaned
        profile.save(update_fields=["avatar"])
        return Response({"avatar": profile.avatar.url if profile.avatar else None},
                        status=status.HTTP_200_OK)


class ChangeEmailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        current_password = request.data.get("current_password")
        new_email = (request.data.get("new_email") or "").strip()

        if not current_password or not new_email:
            return Response({"detail": "current_password and new_email are required."},
                            status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, username=request.user.username, password=current_password)
        if not user:
            return Response({"detail": "Current password is incorrect."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            serializers.EmailField().run_validation(new_email)
        except serializers.ValidationError:
            return Response({"new_email": "Enter a valid email address."},
                            status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email__iexact=new_email).exclude(pk=request.user.pk).exists():
            return Response({"new_email": "This email is already in use."},
                            status=status.HTTP_400_BAD_REQUEST)

        user.email = new_email
        user.save(update_fields=["email"])
        return Response({"detail": "Email updated."}, status=status.HTTP_200_OK)


class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        current_password = request.data.get("current_password")
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if not current_password or not new_password or not confirm_password:
            return Response({"detail": "current_password, new_password, confirm_password are required."},
                            status=status.HTTP_400_BAD_REQUEST)

        if new_password != confirm_password:
            return Response({"confirm_password": "Passwords do not match."},
                            status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, username=request.user.username, password=current_password)
        if not user:
            return Response({"current_password": "Current password is incorrect."},
                            status=status.HTTP_400_BAD_REQUEST)

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as e:
            return Response({"new_password": list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save(update_fields=["password"])
        return Response({"detail": "Password updated. Please log in again."}, status=status.HTTP_200_OK)


class DeactivateAccountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        request.user.is_active = False
        request.user.save(update_fields=["is_active"])
        return Response({"detail": "Account deactivated."}, status=status.HTTP_200_OK)
