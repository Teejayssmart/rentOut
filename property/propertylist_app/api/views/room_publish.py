from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiResponse

from propertylist_app.models import Room, Tenancy
from propertylist_app.api.serializers import DetailResponseSerializer
from .common import ok_response, _listing_state_for_room


class RoomPublishView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="RoomPublishOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(
                        required=False,
                        allow_null=True,
                    ),
                    "data": inline_serializer(
                        name="RoomPublishData",
                        fields={
                            "id": serializers.IntegerField(),
                            "status": serializers.CharField(),
                            "listing_state": serializers.CharField(),
                        },
                    ),
                },
            ),
            401: OpenApiResponse(
                description="Authentication required."
            ),
            403: DetailResponseSerializer,
            404: DetailResponseSerializer,
        },
        description=(
            "Publish an unpublished room listing owned "
            "by the authenticated user."
        ),
    )
    def post(self, request, pk, *args, **kwargs):
        room = get_object_or_404(
            Room.all_objects.filter(is_deleted=False),
            pk=pk,
        )

        if room.property_owner != request.user:
            return Response(
                {
                    "detail": (
                        "You are not allowed to publish this listing."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        today = timezone.localdate()

        # Publishing is decided from the persisted paid entitlement.
        # Hidden listings remain editable, so the authoritative database value
        # must be used rather than relying on lifecycle-filtered object state.
        paid_until = (
            Room.all_objects
            .filter(pk=room.pk, is_deleted=False)
            .values_list("paid_until", flat=True)
            .first()
        )

        if paid_until is None or paid_until < today:
            raise ValidationError(
                {
                    "detail": (
                        "This listing does not have an active paid "
                        "advertising period. Payment is required "
                        "before it can be published."
                    ),
                    "payment_required": True,
                }
            )

        room.paid_until = paid_until

        has_live_tenancy = room.tenancies.filter(
            status__in=[
                Tenancy.STATUS_CONFIRMED,
                Tenancy.STATUS_ACTIVE,
            ],
        ).exists()

        if has_live_tenancy:
            raise ValidationError(
                {
                    "detail": (
                        "This room has a current tenancy and cannot "
                        "be republished as available."
                    )
                }
            )

        update_fields = []

        if room.status != "active":
            room.status = "active"
            update_fields.append("status")

        if not room.is_available:
            room.is_available = True
            update_fields.append("is_available")

        if update_fields:
            update_fields.append("updated_at")
            room.save(update_fields=update_fields)

        return ok_response(
            {
                "id": room.id,
                "status": room.status,
                "listing_state": _listing_state_for_room(room),
            },
            message="Room published successfully.",
            status_code=status.HTTP_200_OK,
        )
