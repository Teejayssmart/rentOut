#Standard/library
from datetime import date, datetime



#Django
from django.db.models import (
    Case,
    CharField,
    Exists,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Value,
    When,
)
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError


#DRF
from rest_framework import generics, permissions, serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.throttling import AnonRateThrottle
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework import filters




#spectacular
from drf_spectacular.utils import extend_schema, OpenApiResponse,OpenApiParameter,OpenApiRequest,inline_serializer
from drf_spectacular.types import OpenApiTypes



#Project
from propertylist_app.models import Room, RoomCategorie, RoomImage, SavedRoom, AvailabilitySlot, Booking
from propertylist_app.services.image import should_auto_approve_upload
from propertylist_app.utils.cached_views import CachedAnonymousGETMixin
from propertylist_app.validators import (
    assert_no_duplicate_files,
    validate_listing_photos,
)
from propertylist_app.api.pagination import StandardLimitOffsetPagination
from propertylist_app.api.permissions import IsAdminOrReadOnly, IsOwnerOrReadOnly
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import standard_response_serializer,standard_paginated_response_serializer
from propertylist_app.api.serializers import (
    AvailabilitySlotSerializer,
    BookingSerializer,
    RoomCategorieSerializer,
    RoomImageSerializer,
    RoomPreviewSerializer,
    RoomSerializer,
    RoomPhotoUploadRequestSerializer,
    AvatarUploadRequestSerializer,
    AvatarUploadResponseSerializer,
    DetailResponseSerializer,
)
from .common import ok_response, _listing_state_for_room, _pagination_meta, _wrap_response_success

class EmptyDataSerializer(serializers.Serializer):
    pass















class RoomCategorieAV(APIView):
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]
    pagination_class = StandardLimitOffsetPagination

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="RoomCategoryListOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": RoomCategorieSerializer(many=True),
                },
            ),
        },
        description="List room categories. Non-staff users only see active categories.",
    )
    def get(self, request):
        qs = RoomCategorie.objects.all().order_by("name")
        if not (request.user and request.user.is_staff):
            qs = qs.filter(active=True)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = RoomCategorieSerializer(page, many=True)

        return _wrap_response_success(
            paginator.get_paginated_response(serializer.data)
        )

    @extend_schema(
        request=RoomCategorieSerializer,
        responses={
            201: inline_serializer(
                name="RoomCategoryCreateOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": RoomCategorieSerializer(),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(description="Admin privileges required."),
        },
        description="Create a room category.",
    )
    def post(self, request):
        ser = RoomCategorieSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return ok_response(
            ser.data,
            message="Room category created successfully.",
            status_code=status.HTTP_201_CREATED,
        )
    


class RoomCategorieDetailAV(APIView):
    permission_classes = [IsAdminOrReadOnly]
    throttle_classes = [AnonRateThrottle]

    @extend_schema(
        responses={
            200: standard_response_serializer("RoomCategorieDetailResponse", RoomCategorieSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        }
    )
    def get(self, request, pk):
        category = get_object_or_404(RoomCategorie, pk=pk)
        return ok_response(
        RoomCategorieSerializer(category).data,
        status_code=status.HTTP_200_OK,
    )

    @extend_schema(
        request=RoomCategorieSerializer,
        responses={
            200: standard_response_serializer(
                "RoomCategorieUpdateResponse",
                RoomCategorieSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def put(self, request, pk):
        category = get_object_or_404(RoomCategorie, pk=pk)
        ser = RoomCategorieSerializer(category, data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return ok_response(
            ser.data,
            message="Room category updated successfully.",
            status_code=status.HTTP_200_OK,
        )

    @extend_schema(
    responses={
        200: standard_response_serializer(
            "RoomCategorieDeleteResponse",
            EmptyDataSerializer,
        ),
        404: OpenApiResponse(response=ErrorResponseSerializer),
    }
    )
    def delete(self, request, pk):
        category = get_object_or_404(RoomCategorie, pk=pk)
        category.delete()

        return ok_response(
            {},
            message="Room category deleted successfully.",
            status_code=status.HTTP_200_OK,
        )    
        
        
class RoomListGV(CachedAnonymousGETMixin, generics.ListAPIView):
    queryset = Room.objects.alive()
    serializer_class = RoomSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["avg_rating", "category__name"]
    pagination_class = StandardLimitOffsetPagination

    cache_prefix = "rooms:list"
    cache_ttl = 60

    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)     
      
      
      
      
      
      
class RoomAV(APIView):
    throttle_classes = [AnonRateThrottle]
    permission_classes = [IsAuthenticatedOrReadOnly]


    @extend_schema(
    operation_id="api_v1_rooms_list",
    responses={
        200: standard_paginated_response_serializer(
            "RoomListResponse",
            RoomSerializer,
        ),
    },
    parameters=[
        OpenApiParameter(name="limit", type=int, location=OpenApiParameter.QUERY, required=False),
        OpenApiParameter(name="offset", type=int, location=OpenApiParameter.QUERY, required=False),
    ],
    description="List active rooms (paid and not expired). Paginated with limit/offset.",
    )
    def get(self, request, *args, **kwargs):
            today = timezone.now().date()

            qs = (
                Room.objects.alive()
                .filter(status="active")
                .filter(Q(paid_until__isnull=True) | Q(paid_until__gte=today))
                .order_by("-id")
            )

            paginator = StandardLimitOffsetPagination()
            page = paginator.paginate_queryset(qs, request, view=self)

            serializer = RoomSerializer(page, many=True, context={"request": request})
            resp = paginator.get_paginated_response(serializer.data)
            return _wrap_response_success(resp)




    @extend_schema(
    request=RoomSerializer,
    responses={
        201: standard_response_serializer(
            "RoomCreateResponse",
            RoomSerializer,
        ),
        400: OpenApiResponse(response=ErrorResponseSerializer),
        401: OpenApiResponse(response=ErrorResponseSerializer),
    },
    description="Create a room owned by the logged-in user.",
    )
    def post(self, request, *args, **kwargs):

        """
        POST /api/v1/rooms/

        Used by the 'List a Room – Step 1' screen.

        - Creates a Room owned by the logged-in user.
        - `action` can be "next" or "save_close" – backend treats them the same;
          the frontend decides what to do next.
        """
        data = request.data.copy()

        # Ignore wizard action flag ("next" / "save_close")
        data.pop("action", None)

        # ---- Basic price validation for the tests ----
        price = data.get("price_per_month")
        if price in (None, "", []):
            return Response(
                {
                    "ok": False,
                    "message": "Validation error.",
                    "errors": {"price_per_month": ["This field is required."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            price_value = float(price)
        except (TypeError, ValueError):
            return Response(
                {
                    "ok": False,
                    "message": "Validation error.",
                    "errors": {"price_per_month": ["A valid number is required."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
)
        if price_value <= 0:
            return Response(
                {
                    "ok": False,
                    "message": "Validation error.",
                    "errors": {"price_per_month": ["Must be greater than 0."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ---- Ensure we always have a category_id for the serializer ----
        if not data.get("category_id"):
            category = (
                RoomCategorie.objects.filter(active=True).order_by("id").first()
                or RoomCategorie.objects.order_by("id").first()
            )
            if not category:
                category, _ = RoomCategorie.objects.get_or_create(
                    name="General", defaults={"active": True}
                )
            data["category_id"] = category.id

        # ---- Force the logged-in user as owner ----
        data["property_owner"] = request.user.id

        serializer = RoomSerializer(data=data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(property_owner=request.user)

        # Return plain DRF object so tests can access response.data["id"]
        return ok_response(
            serializer.data,
            message="Room created successfully.",
            status_code=status.HTTP_201_CREATED,
        )
            

class RoomDetailAV(APIView):
    permission_classes = [IsOwnerOrReadOnly]
    http_method_names = ["get", "put", "patch", "delete"]

    @extend_schema(
        operation_id="api_v1_rooms_retrieve",
        responses={
            200: inline_serializer(
                name="RoomDetailOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": RoomSerializer(),
                },
            ),
            404: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Not found.",
            ),
        },
        description="Retrieve a room by id. Returns ok_response envelope.",
    )
    def get(self, request, pk, *args, **kwargs):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        serializer = RoomSerializer(room, context={"request": request})
        return ok_response(serializer.data, status_code=status.HTTP_200_OK)

    @extend_schema(
        request=RoomSerializer,
        responses={
            200: standard_response_serializer(
                "RoomUpdateResponse",
                RoomSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Replace room fields (owner-only).",
    )
    def put(self, request, pk, *args, **kwargs):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)

        data = request.data.copy()
        data.pop("status", None)
        data.pop("paid_until", None)

        ser = RoomSerializer(room, data=data, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save()

        return ok_response(
            ser.data,
            message="Room updated successfully.",
            status_code=status.HTTP_200_OK,
        )

    @extend_schema(
        request=RoomSerializer,
        responses={
            200: standard_response_serializer(
                "RoomPartialUpdateResponse",
                RoomSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Partial update (owner-only). If action=preview, requires at least 3 photos.",
    )
    def patch(self, request, pk, *args, **kwargs):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)

        data = request.data.copy()

        action = (data.get("action") or "").strip().lower()

        data.pop("action", None)
        data.pop("status", None)
        data.pop("paid_until", None)

        ser = RoomSerializer(
            room,
            data=data,
            partial=True,
            context={"request": request},
        )
        ser.is_valid(raise_exception=True)
        ser.save()

        if action == "preview":
            total_photos = RoomImage.objects.filter(room=room).count()

            if total_photos < 3:
                return Response(
                    {
                        "ok": False,
                        "message": "Please upload at least 3 photos before previewing your listing.",
                        "errors": {
                            "photos_min_required": 3,
                            "photos_current": total_photos,
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return ok_response(
            ser.data,
            message="Room updated successfully.",
            status_code=status.HTTP_200_OK,
        )

    @extend_schema(
    responses={
        200: standard_response_serializer("RoomDeleteResponse", EmptyDataSerializer),
        401: OpenApiResponse(response=ErrorResponseSerializer),
        403: OpenApiResponse(response=ErrorResponseSerializer),
        404: OpenApiResponse(response=ErrorResponseSerializer),
    },
    description="Soft-delete a room (owner-only).",
    )
    def delete(self, request, pk, *args, **kwargs):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        room.soft_delete()

        return ok_response(
            {},
            message="Room deleted successfully.",
            status_code=status.HTTP_200_OK,
        )
        
        
class RoomPreviewView(APIView):
    """
    Step 5/5 – Preview & Edit page

    GET /api/v1/rooms/<pk>/preview/

    Returns:
      {
        "ok": true,
        "message": null,
        "data": {
          "room": { ... },
          "photos": [ ... ]
        }
      }

    Only the room owner is allowed to see this preview payload.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
    responses={
        200: standard_response_serializer(
            "RoomPreviewResponse",
            RoomPreviewSerializer,
        ),
        401: OpenApiResponse(response=ErrorResponseSerializer),
        403: OpenApiResponse(response=ErrorResponseSerializer),
        404: OpenApiResponse(response=ErrorResponseSerializer),
    },
    description="Return the private preview payload for a room owned by the authenticated user.",
    )
    def get(self, request, pk):
        room = get_object_or_404(Room.objects.filter(is_deleted=False), pk=pk)

        # Explicit owner check – preview is private
        if request.user != room.property_owner:
            return Response(
                {
                    "ok": False,
                    "message": "You do not have permission to view this listing preview.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = RoomPreviewSerializer(room, context={"request": request})
        return ok_response(serializer.data, status_code=status.HTTP_200_OK)



class RoomSoftDeleteView(APIView):
    """POST /api/rooms/<id>/soft-delete/"""
    permission_classes = [IsOwnerOrReadOnly]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="RoomSoftDeleteOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="RoomSoftDeleteData",
                        fields={
                            "detail": serializers.CharField(),
                        },
                    ),
                },
            ),
            403: DetailResponseSerializer,
            404: DetailResponseSerializer,
        },
        description="Soft-delete a room owned by the authenticated user.",
    )
    def post(self, request, pk, *args, **kwargs):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        room.soft_delete()
        return ok_response(
            {"detail": f"Room {room.id} soft-deleted."},
            message="Room soft-deleted successfully.",
            status_code=status.HTTP_200_OK,
        )




class RoomUnpublishView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="RoomUnpublishOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="RoomUnpublishData",
                        fields={
                            "id": serializers.IntegerField(),
                            "status": serializers.CharField(),
                            "listing_state": serializers.CharField(),
                        },
                    ),
                },
            ),
            401: OpenApiResponse(description="Authentication required."),
            403: DetailResponseSerializer,
            404: DetailResponseSerializer,
        },
        description="Unpublish a room listing owned by the authenticated user.",
    )
    def post(self, request, pk, *args, **kwargs):
        room = get_object_or_404(Room.objects.filter(is_deleted=False), pk=pk)

        # Only the property owner can unpublish
        if room.property_owner != request.user:
            return Response(
                {"detail": "You are not allowed to unpublish this listing."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Set hidden (unpublished)
        room.status = "hidden"
        room.save(update_fields=["status", "updated_at"])

        return ok_response(
            {
                "id": room.id,
                "status": room.status,
                "listing_state": _listing_state_for_room(room),
            },
            message="Room unpublished successfully.",
            status_code=status.HTTP_200_OK,
        )  
        
        
class RoomPhotoUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        # Anyone can view approved photos; only authenticated owners can upload
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]

    @extend_schema(
        request=None,
        responses={
            200: standard_response_serializer(
                "RoomPhotoListResponse",
                RoomImageSerializer(many=True),
            ),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="List approved room photos. Returns ok_response envelope.",
    )
    def get(self, request, pk):
        """Return only approved images for a room (for grids on Step 4/5, room cards, etc.)."""
        room = get_object_or_404(Room, pk=pk)
        photos = RoomImage.objects.approved().filter(room=room)
        data = RoomImageSerializer(photos, many=True).data

        return ok_response(data, status_code=status.HTTP_200_OK)

    @extend_schema(
        request=OpenApiRequest(
            request=RoomPhotoUploadRequestSerializer,
            encoding={"image": {"contentType": "image/*"}},
        ),
        responses={
            201: standard_response_serializer(
                "RoomPhotoUploadResponse",
                RoomImageSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            403: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Upload a room image. Returns ok_response envelope.",
    )
    def post(self, request, pk):
        """
        Upload a single image for this room.

        Front-end can call this multiple times (one per image) to build the gallery.
        """
        room = get_object_or_404(Room, pk=pk)

        # Owner check
        if room.property_owner_id != request.user.id:
            return Response(
                {
                    "ok": False,
                    "message": "You do not have permission to perform this action.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        file_obj = request.FILES.get("image")
        if not file_obj:
            return Response(
                {
                    "ok": False,
                    "message": "Validation error.",
                    "errors": {"image": ["This field is required."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 1) Quick extension check – JPG / JPEG / PNG only
        allowed_exts = {"jpg", "jpeg", "png", "webp"}
        name_lower = (file_obj.name or "").lower()
        ext = name_lower.rsplit(".", 1)[-1] if "." in name_lower else ""
        if ext not in allowed_exts:
            return Response(
                {
                    "ok": False,
                    "message": "Validation error.",
                    "errors": {"image": ["Only JPG, JPEG, PNG, or WEBP files are allowed."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2) Size/type/duplicate validation (5MB max, uses your existing validator)
        try:
            validate_listing_photos([file_obj], max_mb=5)
            assert_no_duplicate_files([file_obj])
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response(
                {
                    "ok": False,
                    "message": "Validation error.",
                    "errors": {"image": [msg]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3) Autopilot moderation: approve instantly unless flagged
        auto_ok = should_auto_approve_upload(file_obj)
        photo_status = "approved" if auto_ok else "pending"

        # IMPORTANT: ensure file pointer is reset before saving/thumbnail generation
        try:
            file_obj.seek(0)
        except Exception:
            pass

        photo = RoomImage.objects.create(
            room=room,
            image=file_obj,
            status=photo_status,
        )

        return ok_response(
            RoomImageSerializer(photo).data,
            message="Room photo uploaded successfully.",
            status_code=status.HTTP_201_CREATED,
        )               
        
        
        
class RoomPhotoDeleteView(APIView):
    """
    DELETE /api/v1/rooms/<pk>/photos/<photo_id>/  (owner only)
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
    responses={
        200: standard_response_serializer(
            "RoomPhotoDeleteResponse",
            EmptyDataSerializer,
        ),
        401: OpenApiResponse(response=ErrorResponseSerializer),
        403: OpenApiResponse(response=ErrorResponseSerializer),
        404: OpenApiResponse(response=ErrorResponseSerializer),
    }
    )
    def delete(self, request, pk, photo_id):
        room = get_object_or_404(Room, pk=pk)

        owner_id = (
            getattr(room, "property_owner_id", None)
            or getattr(getattr(room, "property_owner", None), "id", None)
        )

        if owner_id != request.user.id:
            return Response(
                {
                    "ok": False,
                    "message": "You do not have permission to perform this action.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        photo = get_object_or_404(RoomImage, pk=photo_id, room=room)
        photo.delete()

        return ok_response(
            {},
            message="Room photo deleted successfully.",
            status_code=status.HTTP_200_OK,
        )



# --------------------
# My Rooms / Search / Nearby
# --------------------
class MyRoomsView(generics.ListAPIView):
    serializer_class = RoomSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardLimitOffsetPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Room.objects.none()
        return Room.objects.alive().filter(property_owner=self.request.user)    
      
      
      
      
# --------------------
# Availability checks & slots
# --------------------
class RoomAvailabilityView(APIView):
    """
    GET /api/rooms/<id>/availability/?from=&to=
    Returns: {"available": bool, "conflicts": [{"id": ..., "start": ..., "end": ...}, ...]}
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        parameters=[
            OpenApiParameter(
                name="from",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Start datetime in ISO 8601 format.",
            ),
            OpenApiParameter(
                name="to",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                required=True,
                description="End datetime in ISO 8601 format.",
            ),
        ],
        responses={
            200: inline_serializer(
                name="RoomAvailabilityResponse",
                fields={
                    "available": serializers.BooleanField(),
                    "conflicts": serializers.ListSerializer(
                        child=inline_serializer(
                            name="RoomAvailabilityConflict",
                            fields={
                                "id": serializers.IntegerField(),
                                "start": serializers.DateTimeField(),
                                "end": serializers.DateTimeField(),
                            },
                        )
                    ),
                },
            ),
            400: inline_serializer(
                name="RoomAvailabilityBadRequest",
                fields={
                    "detail": serializers.CharField(),
                },
            ),
            404: OpenApiResponse(description="Room not found."),
        },
        description="Check whether a room is available between the supplied from/to datetimes.",
    )
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
        return Response({"available": not conflicts_qs.exists(), "conflicts": list(conflicts_qs)})      
      
      
class RoomAvailabilitySlotListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    serializer_class = AvailabilitySlotSerializer

    def _get_room(self):
        room = get_object_or_404(Room.objects.alive(), pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, room)
        return room

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AvailabilitySlot.objects.none()
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

        # AvailabilitySlot belongs to a room, so permissions must check the room
        self.check_object_permissions(self.request, instance.room)

        return super().perform_destroy(instance)     
      
      
      
class RoomAvailabilityPublicView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = AvailabilitySlotSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AvailabilitySlot.objects.none()
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



class RoomListAlt(CachedAnonymousGETMixin, generics.ListAPIView):
    queryset = Room.objects.alive().order_by("-avg_rating")
    serializer_class = RoomSerializer
    permission_classes = [AllowAny]
    cache_timeout = 120  # cache this endpoint for 2 minutes

    @extend_schema(
        request=RoomSerializer,
        responses={
            200: standard_response_serializer(
                "RoomListAltPutResponse",
                RoomSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def put(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        ser = RoomSerializer(room, data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return ok_response(
            ser.data,
            message="Room updated successfully.",
            status_code=status.HTTP_200_OK,
        )

    @extend_schema(
        request=RoomSerializer,
        responses={
            200: standard_response_serializer(
                "RoomListAltPatchResponse",
                RoomSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def patch(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        ser = RoomSerializer(room, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return ok_response(
            ser.data,
            message="Room updated successfully.",
            status_code=status.HTTP_200_OK,
        )

    @extend_schema(
    responses={
        200: standard_response_serializer(
            "RoomListAltDeleteResponse",
            EmptyDataSerializer,
        ),
        401: OpenApiResponse(response=ErrorResponseSerializer),
        403: OpenApiResponse(response=ErrorResponseSerializer),
        404: OpenApiResponse(response=ErrorResponseSerializer),
    }
    )
    def delete(self, request, pk):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        self.check_object_permissions(request, room)
        room.soft_delete()
        return ok_response(
            {},
            message="Room deleted successfully.",
            status_code=status.HTTP_200_OK,
        )


class MyListingsView(generics.ListAPIView):
    """
    Returns the current user's rooms grouped by logical listing_state.
    Front-end will call:
      - /api/my-listings/?state=draft
      - /api/my-listings/?state=active
      - /api/my-listings/?state=expired
      - /api/my-listings/?state=hidden  (optional)
    If no state is given, returns all of the user's listings.
    """
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Room.objects.none()
        user = self.request.user
        today = date.today()

        # Start from all rooms belonging to this user and not soft-deleted
        qs = Room.objects.filter(property_owner=user, is_deleted=False)

        state = self.request.query_params.get("state")

        # Annotate listing_state so serializer can reuse it
        qs = qs.annotate(
            listing_state=Case(
                # draft: no paid_until at all
                When(paid_until__isnull=True, then=Value("draft")),
                # expired: paid_until in the past OR hidden + past paid_until
                When(
                    Q(status="hidden") & Q(paid_until__lt=today),
                    then=Value("expired"),
                ),
                When(paid_until__lt=today, then=Value("expired")),
                # hidden, but not clearly expired
                When(status="hidden", then=Value("hidden")),
                # anything else = active
                default=Value("active"),
                output_field=CharField(),
            )
        )

        if state in ("draft", "active", "expired", "hidden"):
            qs = qs.filter(listing_state=state)

        return qs.order_by("-created_at")



      
      
                            
