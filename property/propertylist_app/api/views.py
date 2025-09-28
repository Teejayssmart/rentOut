import stripe

from datetime import datetime, timedelta

from propertylist_app.services.geo import geocode_postcode_cached

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q, Count, OuterRef, Subquery,Count,Sum
    
from django.shortcuts import get_object_or_404
from django.utils import timezone as dj_tz
from django.utils import timezone


from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import (
    generics,
    permissions,
    status,
    filters,
    viewsets,
    serializers,  # for EmailField validation
)
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny,IsAdminUser
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
    UserProfile,
    RoomImage,
    SavedRoom,
    MessageThread,
    Message,
    MessageRead,
    Booking,
    AvailabilitySlot,
    Payment,
    IdempotencyKey,      # <-- ADDED
    WebhookReceipt,      # <-- ADDED
    Report,
    AuditLog,
    
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
    validate_avatar_image,
    
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
    PaymentSerializer,
    ReportSerializer,
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
stripe.api_key = settings.STRIPE_SECRET_KEY

# --------------------
# Reviews
# --------------------
class UserReview(generics.ListAPIView):
    serializer_class = ReviewSerializer

    def get_queryset(self):
        username = self.request.query_params.get("username", None)
        return Review.objects.filter(review_user__username=username)


class ReviewCreate(generics.CreateAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReviewCreateThrottle]

    def get_queryset(self):
        return Review.objects.all()

    def perform_create(self, serializer):
        room = get_object_or_404(Room, pk=self.kwargs.get("pk"))
        user = self.request.user

        # Block reviewing your own listing (robust to different owner field names)
        owner_id = getattr(room, "property_owner_id", None)
        if owner_id is None:
            owner_obj = (
                getattr(room, "property_owner", None)
                or getattr(room, "owner", None)
                or getattr(room, "landlord", None)
            )
            owner_id = getattr(owner_obj, "id", None)
        if owner_id == user.id:
            raise ValidationError("You cannot review your own room.")

        # One review per user per room
        if Review.objects.filter(room=room, review_user=user).exists():
            raise ValidationError("You have already reviewed this room!")

        # Create the review
        review = serializer.save(room=room, review_user=user)

        # Update rolling average and count on the room
        new_rating = review.rating
        if room.number_rating == 0:
            room.avg_rating = new_rating
        else:
            room.avg_rating = ((room.avg_rating * room.number_rating) + new_rating) / (room.number_rating + 1)
        room.number_rating = room.number_rating + 1
        room.save(update_fields=["avg_rating", "number_rating"])


class ReviewList(generics.ListAPIView):
    serializer_class = ReviewSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["review_user__username", "active"]

    def get_queryset(self):
        pk = self.kwargs["pk"]
        return Review.objects.filter(room=pk)


class ReviewDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer
    permission_classes = [IsReviewUserOrReadOnly]
    throttle_classes = [ScopedRateThrottle, AnonRateThrottle]
    throttle_scope = "review-detail"


# --------------------
# Categories
# --------------------
class RoomCategorieVS(viewsets.ModelViewSet):
    """
    Admin/staff can create/update/delete.
    Non-staff can read, limited to active=True.
    """
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
    ordering_fields = ["avg_rating", "category__name"]
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
        idem_qs=IdempotencyKey.objects,
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
        request_hash=info["request_hash"],
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
        clock_skew=300,
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
    GET /api/search/rooms/
      ?q=<text>
      &min_price=<int>
      &max_price=<int>
      &postcode=<UK_postcode>
      &radius_miles=<int>       # default 10
      &ordering=<field>[,-field]

    Supported ordering:
      - price_per_month, -price_per_month
      - avg_rating, -avg_rating
      - distance_miles, -distance_miles   (only when postcode is supplied)
      - created_at, -created_at           (if your Room model has it; ignored if not)

    Notes:
      - Distance filters/order use **miles** consistently.
      - When postcode is supplied, results are filtered to within radius and
        a .distance_miles attribute is attached for each room (and is orderable).
    """
    serializer_class = RoomSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = RoomLOPagination

    _ordered_ids = None
    _distance_by_id = None

    def get_queryset(self):
        params = self.request.query_params
        q_text      = (params.get("q") or "").strip()
        min_price   = params.get("min_price")
        max_price   = params.get("max_price")
        postcode    = (params.get("postcode") or "").strip()
        raw_radius  = params.get("radius_miles", 10)

        qs = Room.objects.alive()

        # --- Text search (simple icontains over a few fields)
        if q_text:
            qs = qs.filter(
                Q(title__icontains=q_text)
                | Q(description__icontains=q_text)
                | Q(location__icontains=q_text)
            )

        # --- Price filters
        if min_price is not None:
            try:
                qs = qs.filter(price_per_month__gte=int(min_price))
            except Exception:
                raise ValidationError({"min_price": "Must be an integer."})
        if max_price is not None:
            try:
                qs = qs.filter(price_per_month__lte=int(max_price))
            except Exception:
                raise ValidationError({"max_price": "Must be an integer."})

        # --- Optional geo filter (miles consistent)
        self._ordered_ids = None
        self._distance_by_id = None

        if postcode:
            try:
                radius_miles = validate_radius_miles(raw_radius, max_miles=100)
            except ValidationError:
                radius_miles = 10

            # Geocode with caching (service)
            lat, lon = geocode_postcode_cached(postcode)

            # Pre-filter rooms that have coordinates
            base_qs = qs.exclude(latitude__isnull=True).exclude(longitude__isnull=True)

            # Compute distances in Python (keeps it DB-agnostic)
            distances = []
            for r in base_qs.only("id", "latitude", "longitude"):
                d = haversine_miles(lat, lon, r.latitude, r.longitude)
                if d <= radius_miles:
                    distances.append((r.id, d))

            # Order by distance by default if postcode given (unless overridden later)
            distances.sort(key=lambda t: t[1])
            ids_in_radius = [rid for rid, _ in distances]
            self._ordered_ids = ids_in_radius
            self._distance_by_id = {rid: d for rid, d in distances}

            qs = qs.filter(id__in=ids_in_radius)

        # --- Ordering
        ordering_param = (params.get("ordering") or "").strip()

        # Default ordering
        if not ordering_param:
            ordering_param = "-avg_rating" if not postcode else "distance_miles"

        # If distance is requested, apply ordering on the Python-side list in .list()
        # and leave DB ordering neutral to preserve our explicit order.
        if ordering_param in {"distance_miles", "-distance_miles"} and self._ordered_ids is not None:
            # We'll re-order in list()
            pass
        else:
            # Allow a safe subset of model fields for DB ordering
            allowed = {
                "price_per_month": "price_per_month",
                "-price_per_month": "-price_per_month",
                "avg_rating": "avg_rating",
                "-avg_rating": "-avg_rating",
                "created_at": "created_at",
                "-created_at": "-created_at",
            }
            mapped = allowed.get(ordering_param)
            if mapped:
                qs = qs.order_by(mapped)

        return qs

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        # If we've computed distances (when postcode provided)
        if self._distance_by_id is not None:
            room_by_id = {obj.id: obj for obj in queryset}
            ordered_objs = []

            for rid in (self._ordered_ids or []):
                obj = room_by_id.get(rid)
                if obj is not None:
                    obj.distance_miles = self._distance_by_id.get(rid)
                    ordered_objs.append(obj)

            # Check if ordering wants reverse distance
            ordering_param = (request.query_params.get("ordering") or "").strip()
            if ordering_param == "-distance_miles":
                ordered_objs.reverse()

            page = self.paginate_queryset(ordered_objs)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)
            serializer = self.get_serializer(ordered_objs, many=True)
            return Response(serializer.data)

        # No geo distances — fall back to default list
        return super().list(request, *args, **kwargs)



class NearbyRoomsView(generics.ListAPIView):
    """
    GET /api/rooms/nearby/?postcode=<UK_postcode>&radius_miles=<int>

    - Uses cached geocoding (service) and computes distances in **miles** only.
    - Returns rooms within radius; each object gets .distance_miles attached.
    - Supports pagination via RoomLOPagination.
    """
    serializer_class = RoomSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = RoomLOPagination

    _ordered_ids = None
    _distance_by_id = None

    def get_queryset(self):
        postcode_raw = (self.request.query_params.get("postcode") or "").strip()
        if not postcode_raw:
            raise ValidationError({"postcode": "Postcode is required."})

        # Miles only, with validation
        raw_radius = self.request.query_params.get("radius_miles", 10)
        radius_miles = validate_radius_miles(raw_radius, max_miles=100)

        # Geocode (cached)
        lat, lon = geocode_postcode_cached(postcode_raw)

        # Filter to rooms with coordinates
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




class RoomSaveToggleView(APIView):
    """
    POST /api/rooms/<pk>/save-toggle/
    - First call → saves room → {"saved": true,  "saved_at": "<ISO8601>"}
    - Second call → unsaves room → {"saved": false, "saved_at": null}

    Notes:
    - We don’t rely on a SavedRoom timestamp column. When creating, we return
      the current time as 'saved_at'. When removing, we return null.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        obj, created = SavedRoom.objects.get_or_create(user=request.user, room=room)
        if created:
            # New save: return a user-friendly 'saved_at' timestamp
            return Response(
                {"saved": True, "saved_at": timezone.now().isoformat()},
                status=status.HTTP_201_CREATED
            )
        # Already saved → toggle OFF
        obj.delete()
        return Response({"saved": False, "saved_at": None}, status=status.HTTP_200_OK)



class MySavedRoomsView(generics.ListAPIView):
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = RoomLOPagination

    def get_queryset(self):
        """
        Supports ?ordering=... with safe options:
        -saved_at (default), saved_at
        -price_per_month, price_per_month
        -avg_rating, avg_rating
        'saved_at' is derived from the SavedRoom id (no schema change needed).
        """
        user = self.request.user

        # Base: only rooms this user saved
        saved_qs = SavedRoom.objects.filter(user=user)

        # Annotate each Room with 'saved_id' (latest SavedRoom id for this user+room)
        latest_saved_id = (
            SavedRoom.objects
            .filter(user=user, room=OuterRef("pk"))
            .order_by("-id")
            .values("id")[:1]
        )

        qs = (
            Room.objects.alive()
            .filter(id__in=saved_qs.values_list("room_id", flat=True))
            .annotate(saved_id=Subquery(latest_saved_id))
            .select_related("category")
            .prefetch_related("reviews")
        )

        # Map public 'saved_at' to internal 'saved_id'
        ordering = (self.request.query_params.get("ordering") or "-saved_at").strip()
        mapping = {
            "saved_at": "saved_id",
            "-saved_at": "-saved_id",
            "price_per_month": "price_per_month",
            "-price_per_month": "-price_per_month",
            "avg_rating": "avg_rating",
            "-avg_rating": "-avg_rating",
        }
        qs = qs.order_by(mapping.get(ordering, "-saved_id"))
        return qs


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
            id=self.kwargs["thread_id"],
        )
        serializer.save(thread=thread, sender=self.request.user)


class ThreadMarkReadView(APIView):
    """
    POST /api/messages/threads/<thread_id>/read/
    Marks all messages in the thread (not sent by me) as read for the current user.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def post(self, request, thread_id):
        thread = get_object_or_404(
            MessageThread.objects.filter(participants=request.user),
            pk=thread_id
        )

        # Messages I didn't send and haven't marked as read yet
        to_mark = (
            thread.messages
            .exclude(sender=request.user)
            .exclude(reads__user=request.user)
        )

        # Bulk create read records. ignore_conflicts avoids duplicate key errors.
        MessageRead.objects.bulk_create(
            [MessageRead(message=m, user=request.user) for m in to_mark],
            ignore_conflicts=True
        )

        return Response({"marked": to_mark.count()}, status=status.HTTP_200_OK)


class StartThreadFromRoomView(APIView):
    """
    POST /api/rooms/<int:room_id>/start-thread/
    Body (optional): { "body": "Hello, is this room available for viewing?" }

    - Creates (or returns) a 1:1 thread between the current user and the room owner.
    - If 'body' is provided, creates the first message in that thread from the current user.
    - Returns the thread data.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def post(self, request, room_id):
        room = get_object_or_404(Room.objects.alive(), pk=room_id)

        if room.property_owner == request.user:
            return Response(
                {"detail": "You are the owner of this room; no thread needed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Does a 1:1 thread between these two users already exist?
        existing = (
            MessageThread.objects
            .filter(participants=room.property_owner)
            .filter(participants=request.user)
            .annotate(num_participants=Count("participants"))
            .filter(num_participants=2)
            .first()
        )

        if existing:
            thread = existing
        else:
            thread = MessageThread.objects.create()
            thread.participants.set([request.user, room.property_owner])

        # Optional first message
        body = (request.data or {}).get("body", "").strip()
        if body:
            Message.objects.create(thread=thread, sender=request.user, body=body)

        # Return the thread with metadata
        serializer = MessageThreadSerializer(thread, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


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

        conflicts = (
            Booking.objects.filter(room=room, canceled_at__isnull=True)
            .filter(start__lt=end, end__gt=start)
            .exists()
        )
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
            return Response(
                {"detail": "Cannot cancel after booking has started."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking.canceled_at = timezone.now()
        booking.save(update_fields=["canceled_at"])
        return Response(
            {"detail": "Booking cancelled.", "canceled_at": booking.canceled_at},
            status=status.HTTP_200_OK,
        )


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
            return Response(
                {"detail": "Query params 'from' and 'to' are required (ISO 8601)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str)
        except Exception:
            return Response(
                {"detail": "from/to must be ISO 8601 datetimes."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if start >= end:
            return Response(
                {"detail": "'to' must be after 'from'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        conflicts_qs = (
            Booking.objects.filter(room=room, canceled_at__isnull=True)
            .filter(start__lt=end, end__gt=start)
            .values("id", "start", "end")
            .order_by("start")
        )
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
            slot_ids = [
                s.id
                for s in qs
                if Booking.objects.filter(slot=s, canceled_at__isnull=True).count() < s.max_bookings
            ]
            qs = qs.filter(id__in=slot_ids)

        return qs


# --------------------
# Profile utilities
# --------------------
class UserAvatarUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        profile = request.user.profile
        file_obj = self.request.FILES.get("avatar")
        if not file_obj:
            return Response(
                {"avatar": "File is required (form-data key 'avatar')."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cleaned = validate_avatar_image(file_obj)
        profile.avatar = cleaned
        profile.save(update_fields=["avatar"])
        return Response(
            {"avatar": profile.avatar.url if profile.avatar else None},
            status=status.HTTP_200_OK,
        )


class ChangeEmailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        current_password = request.data.get("current_password")
        new_email = (request.data.get("new_email") or "").strip()

        if not current_password or not new_email:
            return Response(
                {"detail": "current_password and new_email are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=request.user.username, password=current_password)
        if not user:
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # validate email format
        try:
            serializers.EmailField().run_validation(new_email)
        except serializers.ValidationError:
            return Response({"new_email": "Enter a valid email address."}, status=status.HTTP_400_BAD_REQUEST)

        # unique email
        if User.objects.filter(email__iexact=new_email).exclude(pk=request.user.pk).exists():
            return Response({"new_email": "This email is already in use."}, status=status.HTTP_400_BAD_REQUEST)

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
            return Response(
                {"detail": "current_password, new_password, confirm_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_password != confirm_password:
            return Response({"confirm_password": "Passwords do not match."}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, username=request.user.username, password=current_password)
        if not user:
            return Response({"current_password": "Current password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)

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


class CreateListingCheckoutSessionView(APIView):
    """
    POST /api/payments/checkout/rooms/<pk>/
    Body: {}
    Creates a £1 Stripe Checkout Session to pay the listing fee for the room.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(Room, pk=pk)

        # only the owner pays for their own room
        if getattr(room, "property_owner_id", None) != request.user.id:
            return Response({"detail": "You can only pay for your own room."},
                            status=status.HTTP_403_FORBIDDEN)

        # amount: £1.00 -> 100 pence
        amount_pence = 100

        # Create a Payment row in 'created' state
        payment = Payment.objects.create(
            user=request.user,
            room=room,
            amount=amount_pence,
            currency="GBP",
            status="created",
        )

        success_url = f"{settings.SITE_URL}/api/payments/success/?session_id={{CHECKOUT_SESSION_ID}}&payment_id={payment.id}"
        cancel_url  = f"{settings.SITE_URL}/api/payments/cancel/?payment_id={payment.id}"

        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=request.user.email or None,
            line_items=[{
                "price_data": {
                    "currency": "gbp",
                    "product_data": {"name": f"Listing fee for: {room.title}"},
                    "unit_amount": amount_pence,
                },
                "quantity": 1,
            }],
            metadata={
                "payment_id": str(payment.id),
                "room_id": str(room.id),
                "user_id": str(request.user.id),
            },
        )

        # store session id
        payment.stripe_checkout_session_id = session.id
        payment.save(update_fields=["stripe_checkout_session_id"])

        return Response({
            "sessionId": session.id,
            "publishableKey": settings.STRIPE_PUBLISHABLE_KEY
        }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        return Response(status=400)  # invalid payload
    except stripe.error.SignatureVerificationError:
        return Response(status=400)  # invalid signature

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        payment_intent = session.get("payment_intent")
        metadata = session.get("metadata") or {}
        payment_id = metadata.get("payment_id")

        if payment_id:
            try:
                payment = Payment.objects.select_related("room", "user").get(id=payment_id)
            except Payment.DoesNotExist:
                return Response(status=200)

            # mark payment succeeded
            payment.status = "succeeded"
            payment.stripe_payment_intent_id = payment_intent or ""
            payment.save(update_fields=["status", "stripe_payment_intent_id"])

            # extend room paid_until by 30 days (or set to 30 if empty)
            room = payment.room
            today = dj_tz.now().date()
            base = room.paid_until if room.paid_until and room.paid_until > today else today
            room.paid_until = base + timedelta(days=30)
            room.save(update_fields=["paid_until"])

    elif event["type"] == "checkout.session.expired":
        session = event["data"]["object"]
        metadata = session.get("metadata") or {}
        payment_id = metadata.get("payment_id")
        if payment_id:
            Payment.objects.filter(id=payment_id, status="created").update(status="canceled")

    return Response(status=200)


class StripeSuccessView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        return Response({"detail": "Payment success received. (Webhook will finalize the room.)"})


class StripeCancelView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        payment_id = request.query_params.get("payment_id")
        if payment_id:
            Payment.objects.filter(id=payment_id, status="created").update(status="canceled")
        return Response({"detail": "Payment canceled."})



class ReportCreateView(generics.CreateAPIView):
    """
    POST /api/reports/
    Body:
    {
      "target_type": "room" | "review" | "message" | "user",
      "object_id": 123,
      "reason": "abuse",
      "details": "…"
    }
    """
    serializer_class = ReportSerializer
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def perform_create(self, serializer):
        report = serializer.save()
        # Audit
        try:
            AuditLog.objects.create(
                actor=self.request.user,
                action="report.create",
                object_type=report.target_type,
                object_id=str(report.object_id),
                meta={"reason": report.reason},
            )
        except Exception:
            pass  # keep reports resilient


class ModerationReportListView(generics.ListAPIView):
    """
    GET /api/moderation/reports/?status=open|in_review|resolved|rejected
    Staff only.
    """
    serializer_class = ReportSerializer
    permission_classes = [IsAdminUser]
    pagination_class = RoomLOPagination

    def get_queryset(self):
        status_q = self.request.query_params.get("status") or "open"
        qs = Report.objects.all().order_by("-created_at")
        if status_q in {"open", "in_review", "resolved", "rejected"}:
            qs = qs.filter(status=status_q)
        return qs


class ModerationReportUpdateView(generics.UpdateAPIView):
    """
    PATCH /api/moderation/reports/<id>/
    Body (any subset):
      { "status": "in_review" | "resolved" | "rejected",
        "resolution_notes": "…",
        "hide_room": true }  # optional, only applies if target is a Room
    """
    serializer_class = ReportSerializer
    permission_classes = [IsAdminUser]
    queryset = Report.objects.all()

    def partial_update(self, request, *args, **kwargs):
        report = self.get_object()
        status_new = request.data.get("status")
        notes = request.data.get("resolution_notes", "")
        hide_room = bool(request.data.get("hide_room"))

        # Update report fields
        if status_new in {"in_review", "resolved", "rejected"}:
            report.status = status_new
        if notes:
            report.resolution_notes = notes
        report.handled_by = request.user
        report.save(update_fields=["status", "resolution_notes", "handled_by", "updated_at"])

        # Optional: hide the room if requested and target is a room
        if hide_room and report.target_type == "room" and isinstance(report.target, Room):
            if report.target.status != "hidden":
                report.target.status = "hidden"
                report.target.save(update_fields=["status"])
            # Audit
            try:
                AuditLog.objects.create(
                    actor=request.user,
                    action="room.hide",
                    object_type="room",
                    object_id=str(report.target.pk),
                    meta={"via_report": report.pk},
                )
            except Exception:
                pass

        # Audit general moderation update
        try:
            AuditLog.objects.create(
                actor=request.user,
                action="report.update",
                object_type=report.target_type,
                object_id=str(report.object_id),
                meta={"status": report.status},
            )
        except Exception:
            pass

        serializer = self.get_serializer(report)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RoomModerationStatusView(APIView):
    """
    PATCH /api/moderation/rooms/<id>/status/
    Body: {"status": "active" | "hidden"}
    Staff only. When set to hidden, the room disappears from all Room.objects.alive() listings.
    """
    permission_classes = [IsAdminUser]

    def patch(self, request, pk):
        room = get_object_or_404(Room, pk=pk)
        status_new = (request.data.get("status") or "").strip()
        if status_new not in {"active", "hidden"}:
            return Response({"status": "Must be 'active' or 'hidden'."}, status=status.HTTP_400_BAD_REQUEST)
        if room.status != status_new:
            room.status = status_new
            room.save(update_fields=["status"])
            # Audit
            try:
                AuditLog.objects.create(
                    actor=request.user,
                    action="room.set_status",
                    object_type="room",
                    object_id=str(room.pk),
                    meta={"status": status_new},
                )
            except Exception:
                pass
        return Response({"id": room.pk, "status": room.status}, status=status.HTTP_200_OK)
    
    
class OpsStatsView(APIView):
    """
    GET /api/ops/stats/
    Admin-only operational snapshot for dashboards.

    Returns:
    {
      "listings": {...},
      "users": {...},
      "bookings": {...},
      "payments": {...},
      "messages": {...},
      "reports": {...},
      "categories": {...}
    }
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        now = timezone.now()
        d7  = now - timedelta(days=7)
        d30 = now - timedelta(days=30)

        # Listings
        total_rooms     = Room.objects.count()
        active_rooms    = Room.objects.filter(status="active", is_deleted=False).count()
        hidden_rooms    = Room.objects.filter(status="hidden", is_deleted=False).count()
        deleted_rooms   = Room.objects.filter(is_deleted=True).count()

        # Users (basic — uses auth model via FK on your models)
        # If you want total users, import and count from get_user_model()
        try:
            from django.contrib.auth import get_user_model
            total_users = get_user_model().objects.count()
        except Exception:
            total_users = None

        # Bookings
        bookings_7d     = Booking.objects.filter(created_at__gte=d7).count()
        bookings_30d    = Booking.objects.filter(created_at__gte=d30).count()
        upcoming_viewings = Booking.objects.filter(start__gte=now, canceled_at__isnull=True).count()

        # Payments (amount stored in pence; convert to GBP)
        payments_30d_count = Payment.objects.filter(status="succeeded", created_at__gte=d30).count()
        payments_30d_sum_p = Payment.objects.filter(status="succeeded", created_at__gte=d30).aggregate(sum_p=Sum("amount"))["sum_p"] or 0
        payments_30d_sum_gbp = round(payments_30d_sum_p / 100.0, 2)

        # Messages (lightweight)
        messages_7d = Message.objects.filter(created_at__gte=d7).count() if hasattr(Message, "created_at") else None
        threads_total = MessageThread.objects.count()

        # Reports queue
        reports_open      = Report.objects.filter(status="open").count() if "Report" in globals() else None
        reports_in_review = Report.objects.filter(status="in_review").count() if "Report" in globals() else None

        # Top categories by active room count
        try:
            top_categories = (
                Room.objects.filter(status="active", is_deleted=False)
                .values("category__id", "category__name")
                .annotate(cnt=Count("id"))
                .order_by("-cnt")[:5]
            )
            top_categories = [
                {"id": r["category__id"], "name": r["category__name"], "count": r["cnt"]}
                for r in top_categories
            ]
        except Exception:
            top_categories = []

        data = {
            "listings": {
                "total": total_rooms,
                "active": active_rooms,
                "hidden": hidden_rooms,
                "deleted": deleted_rooms,
            },
            "users": {
                "total": total_users,
            },
            "bookings": {
                "last_7_days": bookings_7d,
                "last_30_days": bookings_30d,
                "upcoming_viewings": upcoming_viewings,
            },
            "payments": {
                "last_30_days": {
                    "count": payments_30d_count,
                    "sum_gbp": payments_30d_sum_gbp,
                }
            },
            "messages": {
                "last_7_days": messages_7d,
                "threads_total": threads_total,
            },
            "reports": {
                "open": reports_open,
                "in_review": reports_in_review,
            },
            "categories": {
                "top_active": top_categories
            }
        }
        return Response(data, status=status.HTTP_200_OK)
    
