from datetime import datetime, timedelta

from django.apps import apps
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound

from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer

from propertylist_app.models import Tenancy, Review
from propertylist_app.tasks import task_send_tenancy_notification
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import standard_response_serializer
from propertylist_app.api.serializers import (
    TenancyDetailSerializer,
    TenancyRespondSerializer,
    TenancyProposalSerializer,
    StillLivingConfirmResponseSerializer,
    TenancyExtensionCreateSerializer,
    TenancyExtensionRespondSerializer,
    TenancyExtensionResponseSerializer,
    DetailResponseSerializer,
)
from .common import ok_response


def _get_model(app_label: str, model_name: str):
    return apps.get_model(app_label, model_name)





class TenancyStillLivingConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: standard_response_serializer(
                "TenancyStillLivingConfirmResponse",
                StillLivingConfirmResponseSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def patch(self, request, tenancy_id: int, *args, **kwargs):
        Tenancy = apps.get_model("propertylist_app", "Tenancy")

        t = Tenancy.objects.select_related("landlord", "tenant", "room").filter(id=tenancy_id).first()
        if not t:
            return Response(
                {
                    "ok": False,
                    "message": "Not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        user = request.user
        if user.id not in (t.landlord_id, t.tenant_id):
            return Response(
                {
                    "ok": False,
                    "message": "Forbidden.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        now = timezone.now()

        active_status = getattr(Tenancy, "STATUS_ACTIVE", "active")
        if getattr(t, "status", None) != active_status:
            return Response(
                {
                    "ok": False,
                    "message": "Still-living confirmation is only allowed for active tenancies.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        check_at = getattr(t, "still_living_check_at", None)
        if check_at and now < check_at:
            return Response(
                {
                    "ok": False,
                    "message": "Still-living confirmation is not due yet.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated_fields = []

        if user.id == t.tenant_id and getattr(t, "still_living_tenant_confirmed_at", None) is None:
            t.still_living_tenant_confirmed_at = now
            updated_fields.append("still_living_tenant_confirmed_at")

        if user.id == t.landlord_id and getattr(t, "still_living_landlord_confirmed_at", None) is None:
            t.still_living_landlord_confirmed_at = now
            updated_fields.append("still_living_landlord_confirmed_at")

        landlord_done = bool(getattr(t, "still_living_landlord_confirmed_at", None))
        tenant_done = bool(getattr(t, "still_living_tenant_confirmed_at", None))

        if landlord_done and tenant_done and getattr(t, "still_living_confirmed_at", None) is None:
            t.still_living_confirmed_at = now
            updated_fields.append("still_living_confirmed_at")

        if updated_fields:
            t.save(update_fields=updated_fields)

        return ok_response(
            {
                "tenancy_id": t.id,
                "tenant_confirmed": bool(getattr(t, "still_living_tenant_confirmed_at", None)),
                "landlord_confirmed": bool(getattr(t, "still_living_landlord_confirmed_at", None)),
                "confirmed_at": getattr(t, "still_living_confirmed_at", None),
            },
            message="Still-living confirmation recorded successfully.",
            status_code=status.HTTP_200_OK,
        )
        
        



class TenancyExtensionCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=TenancyExtensionCreateSerializer,
        responses={
            201: inline_serializer(
                name="TenancyExtensionCreateOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": TenancyExtensionResponseSerializer(),
                },
            ),
            400: DetailResponseSerializer,
            403: DetailResponseSerializer,
            404: DetailResponseSerializer,
        },
        description="Create a tenancy extension proposal.",
    )
    def post(self, request, tenancy_id: int):
        Tenancy = _get_model("propertylist_app", "Tenancy")
        TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

        tenancy = Tenancy.objects.select_related("landlord", "tenant").filter(id=tenancy_id).first()
        if not tenancy:
            raise NotFound("Tenancy not found.")

        user = request.user
        if user.id not in {tenancy.landlord_id, tenancy.tenant_id}:
            raise PermissionDenied("Forbidden.")

        # Disallow if ended
        ended_statuses = {
            getattr(Tenancy, "STATUS_ENDED", "ended"),
            getattr(Tenancy, "STATUS_CANCELED", "canceled"),
        }
        if getattr(tenancy, "status", None) in ended_statuses:
            raise ValidationError({"detail": "Cannot extend an ended tenancy."})

        ser = TenancyExtensionCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        # Only one open proposal at a time
        open_exists = TenancyExtension.objects.filter(
            tenancy=tenancy,
            status=TenancyExtension.STATUS_PROPOSED,
        ).exists()
        if open_exists:
            raise ValidationError({"detail": "An extension proposal is already open."})

        ext = TenancyExtension.objects.create(
            tenancy=tenancy,
            proposed_by=user,
            proposed_duration_months=ser.validated_data["proposed_duration_months"],
            status=TenancyExtension.STATUS_PROPOSED,
        )

        payload = {
            "id": ext.id,
            "tenancy_id": ext.tenancy_id,
            "proposed_by_user_id": ext.proposed_by_id,
            "proposed_duration_months": ext.proposed_duration_months,
            "status": ext.status,
            "responded_at": ext.responded_at,
            "created_at": ext.created_at,
        }

        return ok_response(
            TenancyExtensionResponseSerializer(payload).data,
            message="Tenancy extension proposal created successfully.",
            status_code=status.HTTP_201_CREATED,
        )   
        
        
        
class TenancyExtensionRespondView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=TenancyExtensionRespondSerializer,
        responses={
            200: standard_response_serializer(
                "TenancyExtensionRespondResponse",
                TenancyExtensionResponseSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            403: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def patch(self, request, tenancy_id: int, extension_id: int):
        Tenancy = _get_model("propertylist_app", "Tenancy")
        TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

        tenancy = Tenancy.objects.select_related("landlord", "tenant").filter(id=tenancy_id).first()
        if not tenancy:
            raise NotFound("Tenancy not found.")

        ext = TenancyExtension.objects.select_related("tenancy").filter(
            id=extension_id,
            tenancy_id=tenancy_id,
        ).first()
        if not ext:
            raise NotFound("Extension not found.")

        user = request.user
        if user.id not in {tenancy.landlord_id, tenancy.tenant_id}:
            raise PermissionDenied("Forbidden.")

        # Only counterparty can respond
        if user.id == ext.proposed_by_id:
            raise PermissionDenied("Proposer cannot respond.")

        if ext.status != TenancyExtension.STATUS_PROPOSED:
            raise ValidationError({"detail": "Extension is not open."})

        ser = TenancyExtensionRespondSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        now = timezone.now()
        action = ser.validated_data["action"]

        if action == "reject":
            ext.status = TenancyExtension.STATUS_REJECTED
            ext.responded_at = now
            ext.save(update_fields=["status", "responded_at"])

        if action == "accept":
            ext.status = TenancyExtension.STATUS_ACCEPTED
            ext.responded_at = now
            ext.save(update_fields=["status", "responded_at"])

            # Apply extension to tenancy
            if hasattr(tenancy, "duration_months"):
                tenancy.duration_months = ext.proposed_duration_months
                tenancy.save(update_fields=["duration_months"])

        payload = {
            "id": ext.id,
            "tenancy_id": ext.tenancy_id,
            "proposed_by_user_id": ext.proposed_by_id,
            "proposed_duration_months": ext.proposed_duration_months,
            "status": ext.status,
            "responded_at": ext.responded_at,
            "created_at": ext.created_at,
        }

        return ok_response(
            TenancyExtensionResponseSerializer(payload).data,
            message="Tenancy extension response recorded successfully.",
            status_code=status.HTTP_200_OK,
        )




class TenancyProposeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=TenancyProposalSerializer,
        responses={
            201: inline_serializer(
                name="TenancyProposeOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": TenancyDetailSerializer(),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Create a tenancy proposal.",
    )
    def post(self, request):
        serializer = TenancyProposalSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        tenancy = serializer.save()

        # Notify the other party (inbox + email via your existing notification system)
        from propertylist_app.tasks import task_send_tenancy_notification
        task_send_tenancy_notification.delay(tenancy.id, "proposed")

        return ok_response(
            TenancyDetailSerializer(tenancy).data,
            message="Tenancy proposal created successfully.",
            status_code=status.HTTP_201_CREATED,
        )
    
    
    
class TenancyRespondView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=TenancyRespondSerializer,
        responses={
            200: inline_serializer(
                name="TenancyRespondOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": TenancyDetailSerializer(),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
            404: DetailResponseSerializer,
        },
        description="Respond to a tenancy proposal and return the updated tenancy.",
    )
    def post(self, request, tenancy_id):
        Tenancy = apps.get_model("propertylist_app", "Tenancy")

        tenancy = (
            Tenancy.objects.select_related("room", "landlord", "tenant")
            .filter(id=tenancy_id)
            .first()
        )
        if not tenancy:
            raise NotFound("Tenancy not found.")
        serializer = TenancyRespondSerializer(
            data=request.data,
            context={"request": request, "tenancy": tenancy},
        )
        serializer.is_valid(raise_exception=True)

        tenancy = serializer.save()

        from propertylist_app.tasks import task_send_tenancy_notification
        if tenancy.status == getattr(Tenancy, "STATUS_CONFIRMED", "confirmed"):
            task_send_tenancy_notification.delay(tenancy.id, "confirmed")
            response_message = "Tenancy confirmed successfully."
        elif tenancy.status == getattr(Tenancy, "STATUS_CANCELLED", "cancelled"):
            task_send_tenancy_notification.delay(tenancy.id, "cancelled")
            response_message = "Tenancy cancelled successfully."
        else:
            task_send_tenancy_notification.delay(tenancy.id, "updated")
            response_message = "Tenancy updated successfully."

        return ok_response(
            TenancyDetailSerializer(tenancy).data,
            message=response_message,
            status_code=status.HTTP_200_OK,
        )               
        
        
        

class MyTenanciesView(ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TenancyDetailSerializer

    def get_queryset(self):
        Tenancy = apps.get_model("propertylist_app", "Tenancy")
        if getattr(self, "swagger_fake_view", False):
            return Tenancy.objects.none()
        user = self.request.user
        return Tenancy.objects.filter(Q(tenant=user) | Q(landlord=user)).order_by("-created_at")



class TenancyStillLivingConfirmResponseSerializer(serializers.Serializer):
    tenancy_id = serializers.IntegerField()
    tenant_confirmed = serializers.BooleanField()
    landlord_confirmed = serializers.BooleanField()
    confirmed_at = serializers.DateTimeField(required=False, allow_null=True)
          
