import logging

from datetime import datetime
from django.db import transaction
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework.throttling import UserRateThrottle
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse,inline_serializer

from propertylist_app.api.pagination import StandardLimitOffsetPagination
from propertylist_app.models import Booking, IdempotencyKey, Room, AvailabilitySlot, UserProfile, Notification
from propertylist_app.validators import ensure_idempotency, validate_no_booking_conflict
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import (
    standard_response_serializer,
    standard_paginated_response_serializer,
)
from propertylist_app.api.serializers import (
    BookingSerializer,
    BookingPreflightRequestSerializer,
    BookingPreflightResponseSerializer,
)
from ..serializers import BookingCreateRequestSerializer, BookingResponseEnvelopeSerializer
from .common import ok_response, _pagination_meta






logger = logging.getLogger(__name__)


class EmptyDataSerializer(serializers.Serializer):
    pass


@extend_schema(
    request=BookingPreflightRequestSerializer,
    responses={
        200: BookingPreflightResponseSerializer,
        400: OpenApiResponse(description="Missing/invalid fields or invalid datetime format."),
        401: OpenApiResponse(description="Authentication required."),
    },
    parameters=[
        OpenApiParameter(
            name="Idempotency-Key",
            type=str,
            location=OpenApiParameter.HEADER,
            required=False,
            description="Optional idempotency key to prevent duplicate booking creation.",
        ),
    ],
    description=(
        "Preflight validation for booking creation. Validates room, start/end datetimes, "
        "and checks for booking conflicts."
    ),
)
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

    return Response(
        {"detail": "Validated. Ready to create booking."},
        status=status.HTTP_200_OK,
    )




# --------------------
# Booking
# --------------------
class BookingListCreateView(generics.ListCreateAPIView):
    """GET my bookings / POST create (slot OR direct)."""
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardLimitOffsetPagination
    throttle_classes = [UserRateThrottle]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ["start", "end", "created_at", "id"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return BookingCreateRequestSerializer
        return BookingSerializer

    @extend_schema(
        request=BookingCreateRequestSerializer,
        responses={
            201: standard_response_serializer(
                "BookingCreateResponse",
                BookingSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Create a booking using either a slot OR room/start/end.",
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        booking = serializer.instance

        return ok_response(
            BookingSerializer(booking, context=self.get_serializer_context()).data,
            message="Booking created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Booking.objects.none()
        user = self.request.user
        qs = Booking.objects.filter(is_deleted=False)

        room_id = self.request.query_params.get("room")
        scope = self.request.query_params.get("scope")

        if not room_id:
            return qs.filter(user=user).order_by("-created_at")

        room = get_object_or_404(Room.objects.alive(), pk=room_id)

        if scope == "viewers":
            if room.property_owner_id != user.id:
                return Booking.objects.none()
            return qs.filter(room=room).order_by("-created_at")

        return qs.filter(user=user, room=room).order_by("-created_at")

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

            profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
            if getattr(profile, "notify_confirmations", True):
                Notification.objects.create(
                    user=self.request.user,
                    type="confirmation",
                    title="Booking confirmed",
                    body="Your booking has been successfully created.",
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

        conflicts = (
            Booking.objects
            .filter(room=room, canceled_at__isnull=True)
            .filter(start__lt=end, end__gt=start)
            .exists()
        )
        if conflicts:
            raise ValidationError({"detail": "Selected dates clash with an existing booking."})

        serializer.save(user=self.request.user, room=room)

        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        if getattr(profile, "notify_confirmations", True):
            Notification.objects.create(
                user=self.request.user,
                type="confirmation",
                title="Booking confirmed",
                body="Your booking has been successfully created.",
            )

    @extend_schema(
        responses={
            200: inline_serializer(
                name="PaginatedBookingListResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": BookingSerializer(many=True),
                    "meta": inline_serializer(
                        name="BookingListMeta",
                        fields={
                            "count": serializers.IntegerField(),
                            "next": serializers.CharField(required=False, allow_null=True),
                            "previous": serializers.CharField(required=False, allow_null=True),
                        },
                    ),
                    "count": serializers.IntegerField(required=False, allow_null=True),
                    "next": serializers.CharField(required=False, allow_null=True),
                    "previous": serializers.CharField(required=False, allow_null=True),
                    "results": BookingSerializer(many=True, required=False),
                },
            )
        },
        parameters=[
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of bookings to return.",
            ),
            OpenApiParameter(
                name="offset",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of bookings to skip before starting the result set.",
            ),
            OpenApiParameter(
                name="room",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter bookings by room id.",
            ),
            OpenApiParameter(
                name="scope",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Optional scope. Use 'viewers' for landlord room viewers mode.",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Sort by start, end, created_at, id, or their descending variants.",
            ),
        ],
        description="List bookings wrapped in ok_response. Supports limit/offset pagination, room filtering, scope filtering, and ordering.",
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            meta = _pagination_meta(self.paginator)
            return ok_response(serializer.data, meta=meta, status_code=200)

        serializer = self.get_serializer(queryset, many=True)
        return ok_response(serializer.data, status_code=200)
    
    
    
    
    
class BookingDetailView(generics.RetrieveAPIView):
    """GET /api/bookings/<id>/ → see my booking"""
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return Booking.objects.filter(is_deleted=False)
        return Booking.objects.filter(user=self.request.user, is_deleted=False)

    @extend_schema(
        responses={
            200: standard_response_serializer(
                "BookingDetailResponse",
                BookingSerializer,
            ),
            401: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Retrieve a booking owned by the authenticated user.",
    )
    def retrieve(self, request, *args, **kwargs):
        resp = super().retrieve(request, *args, **kwargs)
        return _wrap_response_success(resp)



# ======================================================================
# 3) OPTIONAL BUT RECOMMENDED: make BookingCancelView ignore deleted bookings
# FILE: property/propertylist_app/api/views.py
# WHERE: inside BookingCancelView.post()
# REPLACE your first qs line with the 2 lines below
# ======================================================================





class BookingCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="BookingCancelResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="BookingCancelData",
                        fields={
                            "detail": serializers.CharField(),
                            "canceled_at": serializers.DateTimeField(required=False, allow_null=True),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Cancel a booking. Returns ok_response envelope.",
    )
    def post(self, request, pk):
        qs = Booking.objects.filter(is_deleted=False)
        qs = qs if request.user.is_staff else qs.filter(user=request.user)

        booking = get_object_or_404(qs, pk=pk)

        if booking.status == Booking.STATUS_CANCELLED or booking.canceled_at is not None:
            return Response(
                {"detail": "Booking already cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if booking.status == Booking.STATUS_SUSPENDED:
            return Response(
                {"detail": "Suspended bookings cannot be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if booking.start <= timezone.now():
            return Response(
                {"detail": "Cannot cancel after booking has started."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking.status = Booking.STATUS_CANCELLED
        booking.canceled_at = timezone.now()
        booking.save(update_fields=["status", "canceled_at"])

        logger.info(
            "booking_cancel_success booking_id=%s user_id=%s status=%s",
            booking.id,
            request.user.id,
            booking.status,
        )

        return ok_response(
            {
                "detail": "Booking cancelled.",
                "canceled_at": booking.canceled_at,
            },
            status_code=status.HTTP_200_OK,
        )





class BookingSuspendView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="BookingSuspendResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="BookingSuspendData",
                        fields={
                            "id": serializers.IntegerField(),
                            "status": serializers.CharField(),
                            "canceled_at": serializers.DateTimeField(required=False, allow_null=True),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
            403: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Suspend a booking. Returns ok_response envelope.",
    )
    def post(self, request, pk):
        booking = get_object_or_404(Booking, pk=pk, is_deleted=False)

        if booking.user != request.user:
            return Response(
                {
                    "ok": False,
                    "message": "You are not allowed to suspend this booking.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if booking.status == Booking.STATUS_SUSPENDED:
            return Response(
                {"detail": "Booking already suspended."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if booking.status == Booking.STATUS_CANCELLED or booking.canceled_at is not None:
            return Response(
                {"detail": "Cancelled bookings cannot be suspended."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if booking.start <= timezone.now():
            return Response(
                {"detail": "Cannot suspend after booking has started."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if booking.status != Booking.STATUS_ACTIVE:
            return Response(
                {"detail": "Only active bookings can be suspended."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking.status = Booking.STATUS_SUSPENDED
        booking.canceled_at = timezone.now()
        booking.save(update_fields=["status", "canceled_at"])

        logger.info(
            "booking_suspend_success booking_id=%s user_id=%s status=%s",
            booking.id,
            request.user.id,
            booking.status,
        )

        return ok_response(
            {
                "id": booking.id,
                "status": booking.status,
                "canceled_at": booking.canceled_at,
            },
            status_code=status.HTTP_200_OK,
        )
        
class BookingDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: standard_response_serializer(
                "BookingDeleteResponse",
                EmptyDataSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Delete a booking.",
    )
    def delete(self, request, pk, *args, **kwargs):
        qs = Booking.objects.filter(is_deleted=False)

        if not request.user.is_staff:
            qs = qs.filter(
                Q(user=request.user) | Q(room__property_owner=request.user)
            )

        booking = get_object_or_404(qs, pk=pk)

        now = timezone.now()

        if booking.status == Booking.STATUS_SUSPENDED:
            return Response(
                {"detail": "Suspended bookings cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if booking.status == Booking.STATUS_CANCELLED or booking.canceled_at is not None:
            return Response(
                {"detail": "Cancelled bookings cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if booking.start and booking.start <= now:
            return Response(
                {
                    "ok": False,
                    "message": "Cannot delete a booking that has started.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking.is_deleted = True
        booking.deleted_at = now
        booking.save(update_fields=["is_deleted", "deleted_at"])

        logger.info(
            "booking_delete_success booking_id=%s user_id=%s is_deleted=%s",
            booking.id,
            request.user.id,
            booking.is_deleted,
        )

        return ok_response(
            {},
            message="Booking deleted successfully.",
            status_code=status.HTTP_200_OK,
        )



    
