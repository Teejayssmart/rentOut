from datetime import datetime

from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import (
    generics,
    permissions,
    serializers,
    status,
    filters,
    viewsets,
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

from ..models import IdempotencyKey, Booking, RoomImage, WebhookReceipt
from ..validators import (
    ensure_idempotency,
    validate_no_booking_conflict,
    verify_webhook_signature,
    ensure_webhook_not_replayed,
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
)
from propertylist_app.api.throttling import ReviewCreateThrottle, ReviewListThrottle
from propertylist_app.models import Room, RoomCategorie, Review,SavedRoom,MessageThread, Message
from propertylist_app.validators import (
    geocode_postcode,
    haversine_miles,
    validate_radius_miles,
    normalize_uk_postcode,
)
from .serializers import (
    RegistrationSerializer,
    LoginSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    UserSerializer,
    UserProfileSerializer,
    SearchFiltersSerializer,
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
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)  # add 400

class RoomDetailAV(APIView):
    # Allow everyone to read; only the owner (or staff) can modify
    permission_classes = [IsOwnerOrReadOnly]

    def get(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        serializer = RoomSerializer(room)
        return Response(serializer.data)

    def put(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        # enforce owner/staff on write
        self.check_object_permissions(request, room)
        serializer = RoomSerializer(room, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        # enforce owner/staff on write
        self.check_object_permissions(request, room)
        serializer = RoomSerializer(room, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        # enforce owner/staff on write
        self.check_object_permissions(request, room)
        room.soft_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

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
                Q(title__icontains=q) |
                Q(description__icontains=q) |
                Q(location__icontains=q)
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
    serializer_class = RoomSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = RoomLOPagination

    _ordered_ids = None
    _distance_by_id = None

    def get_queryset(self):
        postcode_raw = (self.request.query_params.get("postcode") or "").strip()
        if not postcode_raw:
            raise ValidationError({"postcode": "Postcode is required."})

        # normalise postcode (ValidationError if bad format)
        postcode = normalize_uk_postcode(postcode_raw)

        # validate radius
        raw_radius = self.request.query_params.get("radius_miles", 10)
        radius_miles = validate_radius_miles(raw_radius, max_miles=100)

        # geocode postcode (ValidationError if not found or provider issue)
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
    
class RoomSaveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        obj, created = SavedRoom.objects.get_or_create(user=request.user, room=room)
        return Response({"saved": True}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        SavedRoom.objects.filter(user=request.user, room=room).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# GET /api/users/me/saved/rooms/ — list my saved rooms (paginated)
class MySavedRoomsView(generics.ListAPIView):
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = RoomLOPagination

    def get_queryset(self):
        saved_ids = SavedRoom.objects.filter(user=self.request.user).values_list("room_id", flat=True)
        return (
            Room.objects.alive()
            .filter(id__in=saved_ids)
            .select_related("category")        # tweak these to your schema
            .prefetch_related("reviews")       # if helpful for your serializer
        )

    # ensure serializer gets request for is_saved (optional field)
    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx    


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
    # validated list of participants coming from the client (by username via serializer)
        participants = set(serializer.validated_data.get("participants", []))
        # always include the creator
        participants.add(self.request.user)

        # enforce 1:1 threads (exactly two distinct users)
        if len(participants) != 2:
            raise ValidationError({"participants": "Threads must have exactly 2 participants (you + one other user)."})

        # prevent duplicate threads between the same two users
        existing = (
            MessageThread.objects
            .filter(participants__in=participants)
            .annotate(num_participants=Count("participants"))
            .filter(num_participants=2)
        )
        # ensure both participants are in the same thread (each participant must belong)
        for p in participants:
            existing = existing.filter(participants=p)

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
        # only allow access to threads the user is in
        return Message.objects.filter(thread__id=thread_id, thread__participants=self.request.user)

    def perform_create(self, serializer):
        thread = get_object_or_404(
            MessageThread.objects.filter(participants=self.request.user),
            id=self.kwargs["thread_id"]
        )
        serializer.save(thread=thread, sender=self.request.user)