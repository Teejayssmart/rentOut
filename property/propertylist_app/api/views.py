import json
from datetime import datetime, timedelta

import stripe
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.db.models import Q, Count, OuterRef, Subquery, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

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
from rest_framework.permissions import (
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
    AllowAny,
    IsAdminUser,
)
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

# Services
from propertylist_app.services.geo import geocode_postcode_cached

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
    IdempotencyKey,
    WebhookReceipt,
    Report,
    AuditLog,
)

# Validators / helpers
from propertylist_app.validators import (
    ensure_idempotency,
    validate_no_booking_conflict,
    verify_webhook_signature,
    ensure_webhook_not_replayed,
    haversine_miles,
    validate_radius_miles,
    validate_avatar_image,
)

# API plumbing
from propertylist_app.api.pagination import RoomLOPagination
# (Moved these imports out of class bodies so DRF actually sees them)
from propertylist_app.api.pagination import RoomPagination, RoomCPagination
from propertylist_app.api.permissions import IsAdminOrReadOnly, IsReviewUserOrReadOnly, IsOwnerOrReadOnly
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

# Local serializers
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
        username = self.request.query_params.get("username")
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

        # Prevent self-review
        owner_id = getattr(room, "property_owner_id", None) or getattr(getattr(room, "property_owner", None), "id", None)
        if owner_id == user.id:
            raise ValidationError("You cannot review your own room.")

        # One review per (room, user)
        if Review.objects.filter(room=room, review_user=user).exists():
            raise ValidationError("You have already reviewed this room!")

        review = serializer.save(room=room, review_user=user)

        # Rolling average update
        if room.number_rating == 0:
            room.avg_rating = review.rating
        else:
            room.avg_rating = ((room.avg_rating * room.number_rating) + review.rating) / (room.number_rating + 1)
        room.number_rating += 1
        room.save(update_fields=["avg_rating", "number_rating"])


class ReviewList(generics.ListAPIView):
    serializer_class = ReviewSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["review_user__username", "active"]

    def get_queryset(self):
        return Review.objects.filter(room=self.kwargs["pk"])


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
    """Admin/staff can create/update/delete; others read active=True."""
    serializer_class = RoomCategorieSerializer
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]

    def get_queryset(self):
        qs = RoomCategorie.objects.all().order_by("name")
        if not (getattr(self.request, "user", None) and self.request.user.is_staff):
            qs = qs.filter(active=True)
        return qs


class RoomCategorieAV(APIView):
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]

    def get(self, request):
        qs = RoomCategorie.objects.all().order_by("name")
        if not (request.user and request.user.is_staff):
            qs = qs.filter(active=True)
        return Response(RoomCategorieSerializer(qs, many=True).data)

    def post(self, request):
        ser = RoomCategorieSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data, status=status.HTTP_201_CREATED)


class RoomCategorieDetailAV(APIView):
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]

    def get(self, request, pk):
        category = get_object_or_404(RoomCategorie, pk=pk)
        return Response(RoomCategorieSerializer(category).data)

    def put(self, request, pk):
        category = get_object_or_404(RoomCategorie, pk=pk)
        ser = RoomCategorieSerializer(category, data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

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
        return Response(RoomSerializer(Room.objects.alive(), many=True).data)

    def post(self, request):
        ser = RoomSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(property_owner=request.user)
        return Response(ser.data, status=status.HTTP_201_CREATED)
    # NOTE: pagination/order settings on APIView are ignored by DRF; use RoomListGV for that.


class RoomDetailAV(APIView):
    permission_classes = [IsOwnerOrReadOnly]

    def get(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        return Response(RoomSerializer(room).data)

    def put(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        ser = RoomSerializer(room, data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    def patch(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        ser = RoomSerializer(room, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    def delete(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        room.soft_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoomSoftDeleteView(APIView):
    """POST /api/rooms/<id>/soft-delete/"""
    permission_classes = [IsOwnerOrReadOnly]

    def post(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        room.soft_delete()
        return Response({"detail": f"Room {room.id} soft-deleted."})


# --------------------
# Idempotent booking validation (legacy pre-flight)
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
        return Response({"detail": "room, start, and end are required."}, status=status.HTTP_400_BAD_REQUEST)

    room = get_object_or_404(Room, pk=room_id)
    try:
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
    except Exception:
        return Response({"detail": "start and end must be ISO 8601 datetimes."}, status=status.HTTP_400_BAD_REQUEST)

    Booking.objects.select_for_update().filter(room=room)  # lock scope
    validate_no_booking_conflict(room, start_dt, end_dt, Booking.objects)

    IdempotencyKey.objects.create(
        user_id=request.user.id,
        key=key,
        action="create_booking",
        request_hash=info["request_hash"],
    )
    return Response({"detail": "Validated. Ready to create booking."})


# --------------------
# Generic webhook entry (optional)
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
    return Response({"ok": True})


class ProviderWebhookView(APIView):
    """
    POST /api/webhooks/<provider>/incoming/
    Verifies HMAC signature, prevents replay, logs payload, and dispatches.
    """
    permission_classes = [AllowAny]

    def post(self, request, provider):
        raw_body = request.body or b""
        provider_key = (provider or "default").strip().lower()

        secret = (
            settings.WEBHOOK_SECRETS.get(provider_key)
            or settings.WEBHOOK_SECRETS.get("default")
            or ""
        )
        if not secret:
            return Response(
                {"detail": f"No webhook secret configured for provider '{provider_key}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sig_header = request.headers.get("Stripe-Signature") or request.headers.get("X-Signature") or ""
        try:
            verify_webhook_signature(
                secret=secret, payload=raw_body, signature_header=sig_header, scheme="sha256=", clock_skew=300
            )
        except Exception as e:
            return Response({"detail": f"signature verification failed: {e}"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        event_id = (
            request.headers.get("X-Event-Id")
            or (payload.get("id") if isinstance(payload, dict) else None)
            or ""
        )
        if not event_id:
            import hashlib
            event_id = hashlib.sha256(raw_body).hexdigest()

        try:
            ensure_webhook_not_replayed(event_id, WebhookReceipt.objects)
        except Exception:
            return Response({"ok": True, "duplicate": True})

        try:
            hdrs = {
                "User-Agent": request.headers.get("User-Agent"),
                "Stripe-Signature": request.headers.get("Stripe-Signature"),
                "X-Signature": request.headers.get("X-Signature"),
                "X-Event-Id": request.headers.get("X-Event-Id"),
                "Content-Type": request.headers.get("Content-Type"),
            }
            WebhookReceipt.objects.create(source=provider_key, event_id=event_id, payload=payload, headers=hdrs)
        except Exception:
            pass

        if provider_key == "stripe":
            return self._handle_stripe(payload)
        return Response({"ok": True})

    def _handle_stripe(self, payload: dict):
        """Handles minimal Stripe events used by your app."""
        try:
            evt_type = payload.get("type")
            data_obj = (payload.get("data") or {}).get("object") or {}
        except Exception:
            return Response({"ok": True, "note": "malformed stripe payload"})

        if evt_type == "checkout.session.completed":
            session = data_obj
            payment_intent = session.get("payment_intent") or ""
            metadata = session.get("metadata") or {}
            payment_id = metadata.get("payment_id")

            if payment_id:
                try:
                    payment = Payment.objects.select_related("room", "user").get(id=payment_id)
                except Payment.DoesNotExist:
                    return Response({"ok": True, "note": "payment not found"})

                payment.status = "succeeded"
                payment.stripe_payment_intent_id = payment_intent
                payment.save(update_fields=["status", "stripe_payment_intent_id"])

                room = payment.room
                if room:
                    today = timezone.localdate()
                    base = room.paid_until if room.paid_until and room.paid_until > today else today
                    room.paid_until = base + timedelta(days=30)
                    room.save(update_fields=["paid_until"])

            return Response({"ok": True})

        if evt_type == "checkout.session.expired":
            session = data_obj
            metadata = session.get("metadata") or {}
            payment_id = metadata.get("payment_id")
            if payment_id:
                Payment.objects.filter(id=payment_id, status="created").update(status="canceled")
            return Response({"ok": True})

        return Response({"ok": True, "note": f"ignored {evt_type}"})


# --------------------
# Auth / Profile
# --------------------
class RegistrationView(generics.CreateAPIView):
    serializer_class = RegistrationSerializer
    permission_classes = [permissions.AllowAny]


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        user = authenticate(request, username=ser.validated_data["username"], password=ser.validated_data["password"])
        if not user:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_400_BAD_REQUEST)

        refresh = RefreshToken.for_user(user)
        return Response({"refresh": str(refresh), "access": str(refresh.access_token)})


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response({"detail": "Refresh token required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh).blacklist()
        except Exception:
            return Response({"detail": "Invalid or expired refresh token."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Logged out."})


class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = PasswordResetRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response({"detail": "Password reset email would be sent"})


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = PasswordResetConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
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

    def _get_room(self):
        room = get_object_or_404(Room, pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, room)
        return room

    def perform_create(self, serializer):
        room = self._get_room()
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
    pagination_class = RoomLOPagination

    def get_queryset(self):
        return Room.objects.alive().filter(property_owner=self.request.user)


class SearchRoomsView(generics.ListAPIView):
    """
    GET /api/search/rooms/?q=&min_price=&max_price=&postcode=&radius_miles=&ordering=
    ordering: price_per_month, -price_per_month, avg_rating, -avg_rating,
              distance_miles, -distance_miles, created_at, -created_at
    """
    serializer_class = RoomSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = RoomLOPagination

    _ordered_ids = None
    _distance_by_id = None

    def get_queryset(self):
        params = self.request.query_params
        q_text = (params.get("q") or "").strip()
        min_price = params.get("min_price")
        max_price = params.get("max_price")
        postcode = (params.get("postcode") or "").strip()
        raw_radius = params.get("radius_miles", 10)

        qs = Room.objects.alive()

        if q_text:
            qs = qs.filter(Q(title__icontains=q_text) | Q(description__icontains=q_text) | Q(location__icontains=q_text))

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

        self._ordered_ids = None
        self._distance_by_id = None

        if postcode:
            try:
                radius_miles = validate_radius_miles(raw_radius, max_miles=100)
            except ValidationError:
                radius_miles = 10

            lat, lon = geocode_postcode_cached(postcode)

            base_qs = qs.exclude(latitude__isnull=True).exclude(longitude__isnull=True)

            distances = []
            for r in base_qs.only("id", "latitude", "longitude"):
                d = haversine_miles(lat, lon, r.latitude, r.longitude)
                if d <= radius_miles:
                    distances.append((r.id, d))

            distances.sort(key=lambda t: t[1])
            ids_in_radius = [rid for rid, _ in distances]
            self._ordered_ids = ids_in_radius
            self._distance_by_id = {rid: d for rid, d in distances}
            qs = qs.filter(id__in=ids_in_radius)

        ordering_param = (params.get("ordering") or "").strip()
        if not ordering_param:
            ordering_param = "distance_miles" if postcode else "-avg_rating"

        if ordering_param in {"distance_miles", "-distance_miles"} and self._ordered_ids is not None:
            # handled in list()
            pass
        else:
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

        if self._distance_by_id is not None:
            room_by_id = {obj.id: obj for obj in queryset}
            ordered_objs = []
            for rid in (self._ordered_ids or []):
                obj = room_by_id.get(rid)
                if obj is not None:
                    obj.distance_miles = self._distance_by_id.get(rid)
                    ordered_objs.append(obj)

            ordering_param = (request.query_params.get("ordering") or "").strip()
            if ordering_param == "-distance_miles":
                ordered_objs.reverse()

            page = self.paginate_queryset(ordered_objs)
            if page is not None:
                ser = self.get_serializer(page, many=True)
                return self.get_paginated_response(ser.data)
            ser = self.get_serializer(ordered_objs, many=True)
            return Response(ser.data)

        return super().list(request, *args, **kwargs)


class NearbyRoomsView(generics.ListAPIView):
    """
    GET /api/rooms/nearby/?postcode=<UK_postcode>&radius_miles=<int>
    Miles only; attaches .distance_miles to each room.
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

        radius_miles = validate_radius_miles(self.request.query_params.get("radius_miles", 10), max_miles=100)
        lat, lon = geocode_postcode_cached(postcode_raw)

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
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = self.get_serializer(ordered_objs, many=True)
        return Response(ser.data)


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
    First call saves, second call unsaves.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        obj, created = SavedRoom.objects.get_or_create(user=request.user, room=room)
        if created:
            return Response({"saved": True, "saved_at": timezone.now().isoformat()}, status=status.HTTP_201_CREATED)
        obj.delete()
        return Response({"saved": False, "saved_at": None})


class MySavedRoomsView(generics.ListAPIView):
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = RoomLOPagination

    def get_queryset(self):
        user = self.request.user
        saved_qs = SavedRoom.objects.filter(user=user)

        latest_saved_id = (
            SavedRoom.objects.filter(user=user, room=OuterRef("pk")).order_by("-id").values("id")[:1]
        )

        qs = (
            Room.objects.alive()
            .filter(id__in=saved_qs.values_list("room_id", flat=True))
            .annotate(saved_id=Subquery(latest_saved_id))
            .select_related("category")
            .prefetch_related("reviews")
        )

        ordering = (self.request.query_params.get("ordering") or "-saved_at").strip()
        mapping = {
            "saved_at": "saved_id",
            "-saved_at": "-saved_id",
            "price_per_month": "price_per_month",
            "-price_per_month": "-price_per_month",
            "avg_rating": "avg_rating",
            "-avg_rating": "-avg_rating",
        }
        return qs.order_by(mapping.get(ordering, "-saved_id"))

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx


# --------------------
# Messaging
# --------------------
class MessageThreadListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/messages/threads/"""
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
            MessageThread.objects.filter(participants=p_list[0])
            .filter(participants=p_list[1])
            .annotate(num_participants=Count("participants"))
            .filter(num_participants=2)
        )
        if existing.exists():
            raise ValidationError({"detail": "A thread between you two already exists."})

        thread = serializer.save()
        thread.participants.set(participants)


class MessageListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/messages/threads/<thread_id>/messages/"""
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    # Use cursor pagination for smooth scrolling (import at top)
    pagination_class = RoomCPagination
    throttle_classes = [UserRateThrottle]

    # Sorting: newest activity first
    ordering_fields = ["updated", "created", "id"]
    ordering = ["-updated"]

    def get_queryset(self):
        thread_id = self.kwargs["thread_id"]
        return Message.objects.filter(thread__id=thread_id, thread__participants=self.request.user)

    def perform_create(self, serializer):
        thread = get_object_or_404(MessageThread.objects.filter(participants=self.request.user), id=self.kwargs["thread_id"])
        serializer.save(thread=thread, sender=self.request.user)


class ThreadMarkReadView(APIView):
    """POST /api/messages/threads/<thread_id>/read/ — marks all inbound messages as read."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def post(self, request, thread_id):
        thread = get_object_or_404(MessageThread.objects.filter(participants=request.user), pk=thread_id)

        to_mark = thread.messages.exclude(sender=request.user).exclude(reads__user=request.user)
        MessageRead.objects.bulk_create([MessageRead(message=m, user=request.user) for m in to_mark], ignore_conflicts=True)

        return Response({"marked": to_mark.count()})


class StartThreadFromRoomView(APIView):
    """
    POST /api/rooms/<int:room_id>/start-thread/
    Body (optional): { "body": "Hello, is this room available for viewing?" }
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def post(self, request, room_id):
        room = get_object_or_404(Room.objects.alive(), pk=room_id)
        if room.property_owner == request.user:
            return Response({"detail": "You are the owner of this room; no thread needed."}, status=status.HTTP_400_BAD_REQUEST)

        existing = (
            MessageThread.objects.filter(participants=room.property_owner)
            .filter(participants=request.user)
            .annotate(num_participants=Count("participants"))
            .filter(num_participants=2)
            .first()
        )
        thread = existing or MessageThread.objects.create()
        if not existing:
            thread.participants.set([request.user, room.property_owner])

        body = (request.data or {}).get("body", "").strip()
        if body:
            Message.objects.create(thread=thread, sender=request.user, body=body)

        return Response(MessageThreadSerializer(thread, context={"request": request}).data)


# --------------------
# Bookings (viewing requests)
# --------------------
class BookingListCreateView(generics.ListCreateAPIView):
    """GET my bookings / POST create."""
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = RoomLOPagination
    throttle_classes = [UserRateThrottle]

    # Enable ordering via query param (?ordering=-created_at or ?ordering=start)
    ordering_fields = ["created_at", "start"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Booking.objects.filter(user=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
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
            return

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

        conflicts = Booking.objects.filter(room=room, canceled_at__isnull=True).filter(start__lt=end, end__gt=start).exists()
        if conflicts:
            raise ValidationError({"detail": "Selected dates clash with an existing booking."})

        serializer.save(user=self.request.user, room=room)


class BookingDetailView(generics.RetrieveAPIView):
    """GET /api/bookings/<id>/ → see my booking"""
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.all() if self.request.user.is_staff else Booking.objects.filter(user=self.request.user)


class BookingCancelView(APIView):
    """POST /api/bookings/<id>/cancel/ — soft-cancel a booking."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        qs = Booking.objects.all() if request.user.is_staff else Booking.objects.filter(user=request.user)
        booking = get_object_or_404(qs, pk=pk)

        if booking.canceled_at:
            return Response({"detail": "Booking already cancelled."})

        if booking.start <= timezone.now():
            return Response({"detail": "Cannot cancel after booking has started."}, status=status.HTTP_400_BAD_REQUEST)

        booking.canceled_at = timezone.now()
        booking.save(update_fields=["canceled_at"])
        return Response({"detail": "Booking cancelled.", "canceled_at": booking.canceled_at})


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
            return Response({"detail": "Query params 'from' and 'to' are required (ISO 8601)."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str)
        except Exception:
            return Response({"detail": "from/to must be ISO 8601 datetimes."}, status=status.HTTP_400_BAD_REQUEST)
        if start >= end:
            return Response({"detail": "'to' must be after 'from'."}, status=status.HTTP_400_BAD_REQUEST)

        conflicts_qs = (
            Booking.objects.filter(room=room, canceled_at__isnull=True)
            .filter(start__lt=end, end__gt=start)
            .values("id", "start", "end")
            .order_by("start")
        )
        return Response({"available": not conflicts_qs.exists(), "conflicts": list(conflicts_qs)})


class RoomAvailabilitySlotListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    serializer_class = AvailabilitySlotSerializer

    def _get_room(self):
        room = get_object_or_404(Room.objects.alive(), pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, room)
        return room

    def get_queryset(self):
        room = get_object_or_404(Room.objects.alive(), pk=self.kwargs["pk"])
        return room.availability_slots.order_by("start")

    def perform_create(self, serializer):
        room = self._get_room()
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
            available_ids = [
                s.id for s in qs if Booking.objects.filter(slot=s, canceled_at__isnull=True).count() < s.max_bookings
            ]
            qs = qs.filter(id__in=available_ids)

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
            return Response({"avatar": "File is required (form-data key 'avatar')."}, status=status.HTTP_400_BAD_REQUEST)
        cleaned = validate_avatar_image(file_obj)
        profile.avatar = cleaned
        profile.save(update_fields=["avatar"])
        return Response({"avatar": profile.avatar.url if profile.avatar else None})


class ChangeEmailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        current_password = request.data.get("current_password")
        new_email = (request.data.get("new_email") or "").strip()

        if not current_password or not new_email:
            return Response({"detail": "current_password and new_email are required."}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, username=request.user.username, password=current_password)
        if not user:
            return Response({"detail": "Current password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            serializers.EmailField().run_validation(new_email)
        except serializers.ValidationError:
            return Response({"new_email": "Enter a valid email address."}, status=status.HTTP_400_BAD_REQUEST)

        if get_user_model().objects.filter(email__iexact=new_email).exclude(pk=request.user.pk).exists():
            return Response({"new_email": "This email is already in use."}, status=status.HTTP_400_BAD_REQUEST)

        user.email = new_email
        user.save(update_fields=["email"])
        return Response({"detail": "Email updated."})


class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        current_password = request.data.get("current_password")
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if not current_password or not new_password or not confirm_password:
            return Response({"detail": "current_password, new_password, confirm_password are required."}, status=status.HTTP_400_BAD_REQUEST)

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
        return Response({"detail": "Password updated. Please log in again."})


class DeactivateAccountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        request.user.is_active = False
        request.user.save(update_fields=["is_active"])
        return Response({"detail": "Account deactivated."})


# --------------------
# Stripe payments (GBP stored in Payment.amount)
# --------------------
class CreateListingCheckoutSessionView(APIView):
    """
    POST /api/payments/checkout/rooms/<pk>/
    Creates a £1 Stripe Checkout Session (line item in pence; Payment.amount stored in GBP).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(Room, pk=pk)

        if getattr(room, "property_owner_id", None) != request.user.id:
            return Response({"detail": "You can only pay for your own room."}, status=status.HTTP_403_FORBIDDEN)

        amount_gbp = 1.00        # store GBP in DB
        amount_pence = 100       # Stripe expects pence

        payment = Payment.objects.create(
            user=request.user,
            room=room,
            amount=amount_gbp,   # GBP in your model
            currency="GBP",
            status="created",
        )

        success_url = f"{settings.SITE_URL}/api/payments/success/?session_id={{CHECKOUT_SESSION_ID}}&payment_id={payment.id}"
        cancel_url = f"{settings.SITE_URL}/api/payments/cancel/?payment_id={payment.id}"

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

        payment.stripe_checkout_session_id = session.id
        payment.save(update_fields=["stripe_checkout_session_id"])

        return Response({"sessionId": session.id, "publishableKey": settings.STRIPE_PUBLISHABLE_KEY})


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload, sig_header=sig_header, secret=settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return Response(status=400)

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

            payment.status = "succeeded"
            payment.stripe_payment_intent_id = payment_intent or ""
            payment.save(update_fields=["status", "stripe_payment_intent_id"])

            room = payment.room
            if room:
                today = timezone.now().date()
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
        return Response({"detail": "Payment success received. (Webhook will finalise the room.)"})


class StripeCancelView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        payment_id = request.query_params.get("payment_id")
        if payment_id:
            Payment.objects.filter(id=payment_id, status="created").update(status="canceled")
        return Response({"detail": "Payment canceled."})


# --------------------
# Reports / Moderation
# --------------------
class ReportCreateView(generics.CreateAPIView):
    """
    POST /api/reports/
    Body:
      {"target_type": "room"|"review"|"message"|"user", "object_id": 123, "reason": "abuse", "details": "…"}
    """
    serializer_class = ReportSerializer
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def perform_create(self, serializer):
        report = serializer.save()
        # Audit (align with AuditLog model fields)
        try:
            AuditLog.objects.create(
                user=self.request.user,
                action="report.create",
                ip_address=getattr(self.request, "META", {}).get("REMOTE_ADDR"),
                extra_data={"target_type": report.target_type, "object_id": report.object_id, "reason": report.reason},
            )
        except Exception:
            pass


class ModerationReportListView(generics.ListAPIView):
    """GET /api/moderation/reports/?status=open|in_review|resolved|rejected — staff only."""
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
    Body (any subset): {"status": "...", "resolution_notes": "...", "hide_room": true}
    """
    serializer_class = ReportSerializer
    permission_classes = [IsAdminUser]
    queryset = Report.objects.all()

    def partial_update(self, request, *args, **kwargs):
        report = self.get_object()
        status_new = request.data.get("status")
        notes = request.data.get("resolution_notes", "")
        hide_room = bool(request.data.get("hide_room"))

        if status_new in {"in_review", "resolved", "rejected"}:
            report.status = status_new
        if notes:
            report.resolution_notes = notes
        report.handled_by = request.user
        report.save(update_fields=["status", "resolution_notes", "handled_by", "updated_at"])

        if hide_room and report.target_type == "room" and isinstance(report.target, Room):
            if report.target.status != "hidden":
                report.target.status = "hidden"
                report.target.save(update_fields=["status"])
            try:
                AuditLog.objects.create(
                    user=request.user,
                    action="room.hide",
                    ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                    extra_data={"via_report": report.pk, "room_id": report.target.pk},
                )
            except Exception:
                pass

        try:
            AuditLog.objects.create(
                user=request.user,
                action="report.update",
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                extra_data={"status": report.status, "target_type": report.target_type, "object_id": report.object_id},
            )
        except Exception:
            pass

        return Response(self.get_serializer(report).data)


class RoomModerationStatusView(APIView):
    """
    PATCH /api/moderation/rooms/<id>/status/
    Body: {"status": "active"|"hidden"} — staff only.
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
            try:
                AuditLog.objects.create(
                    user=request.user,
                    action="room.set_status",
                    ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                    extra_data={"room_id": room.pk, "status": status_new},
                )
            except Exception:
                pass
        return Response({"id": room.pk, "status": room.status})


# --------------------
# Ops snapshot
# --------------------
class OpsStatsView(APIView):
    """
    GET /api/ops/stats/ — admin-only operational snapshot.
    Amounts reported in **GBP** (Payment.amount is stored in GBP).
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        now = timezone.now()
        d7 = now - timedelta(days=7)
        d30 = now - timedelta(days=30)

        total_rooms = Room.objects.count()
        active_rooms = Room.objects.filter(status="active", is_deleted=False).count()
        hidden_rooms = Room.objects.filter(status="hidden", is_deleted=False).count()
        deleted_rooms = Room.objects.filter(is_deleted=True).count()

        try:
            total_users = get_user_model().objects.count()
        except Exception:
            total_users = None

        bookings_7d = Booking.objects.filter(created_at__gte=d7).count()
        bookings_30d = Booking.objects.filter(created_at__gte=d30).count()
        upcoming_viewings = Booking.objects.filter(start__gte=now, canceled_at__isnull=True).count()

        # Payment.amount stored in GBP, so no /100 conversion here.
        payments_30d_count = Payment.objects.filter(status="succeeded", created_at__gte=d30).count()
        payments_30d_sum_gbp = float(
            Payment.objects.filter(status="succeeded", created_at__gte=d30).aggregate(sum_amt=Sum("amount"))["sum_amt"]
            or 0
        )

        messages_7d = Message.objects.filter(created_at__gte=d7).count()
        threads_total = MessageThread.objects.count()

        reports_open = Report.objects.filter(status="open").count()
        reports_in_review = Report.objects.filter(status="in_review").count()

        try:
            top_categories = (
                Room.objects.filter(status="active", is_deleted=False)
                .values("category__id", "category__name")
                .annotate(cnt=Count("id"))
                .order_by("-cnt")[:5]
            )
            top_categories = [{"id": r["category__id"], "name": r["category__name"], "count": r["cnt"]} for r in top_categories]
        except Exception:
            top_categories = []

        data = {
            "listings": {"total": total_rooms, "active": active_rooms, "hidden": hidden_rooms, "deleted": deleted_rooms},
            "users": {"total": total_users},
            "bookings": {"last_7_days": bookings_7d, "last_30_days": bookings_30d, "upcoming_viewings": upcoming_viewings},
            "payments": {"last_30_days": {"count": payments_30d_count, "sum_gbp": round(payments_30d_sum_gbp, 2)}},
            "messages": {"last_7_days": messages_7d, "threads_total": threads_total},
            "reports": {"open": reports_open, "in_review": reports_in_review},
            "categories": {"top_active": top_categories},
        }
        return Response(data)
