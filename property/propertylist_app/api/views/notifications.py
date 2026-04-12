
from django.shortcuts import get_object_or_404

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer

from propertylist_app.models import Notification, UserProfile
from propertylist_app.api.pagination import StandardLimitOffsetPagination
from propertylist_app.api.serializers import (
    NotificationSerializer,
    NotificationPreferencesSerializer,
)
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import standard_response_serializer

from .common import ok_response, _wrap_response_success






class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardLimitOffsetPagination

    @extend_schema(
        responses={
            200: inline_serializer(
                name="NotificationListOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": NotificationSerializer(many=True),
                },
            ),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="List notifications for the current user. Returns ok_response envelope (not paginated).",
    )
    def get(self, request):
        qs = Notification.objects.filter(user=request.user).order_by("is_read", "-created_at")

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        data = NotificationSerializer(page, many=True).data

        return _wrap_response_success(
            paginator.get_paginated_response(data)
        )
    
    

class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="NotificationMarkReadOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="NotificationMarkReadData",
                        fields={
                            "ok": serializers.BooleanField(),
                        },
                    ),
                },
            ),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Notification not found."),
        },
        description="Mark a notification as read for the current user.",
    )
    def post(self, request, pk: int):
        notif = get_object_or_404(Notification, pk=pk, user=request.user)

        if not notif.is_read:
            notif.is_read = True
            notif.save(update_fields=["is_read"])

        return ok_response(
            {"ok": True},
            status_code=status.HTTP_200_OK,
        )


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="NotificationMarkAllReadOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="NotificationMarkAllReadData",
                        fields={
                            "marked": serializers.IntegerField(),
                        },
                    ),
                },
            ),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Mark all notifications as read for the current user.",
    )
    def post(self, request):
        updated_count = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).update(is_read=True)

        return ok_response(
            {"marked": updated_count},
            status_code=status.HTTP_200_OK,
        )
    
    
    
class MyNotificationPreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: inline_serializer(
                name="NotificationPreferencesOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": NotificationPreferencesSerializer(),
                },
            ),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Get current user's notification preferences.",
    )
    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        ser = NotificationPreferencesSerializer(profile)
        return ok_response(ser.data)

    @extend_schema(
        request=NotificationPreferencesSerializer,
        responses={
            200: standard_response_serializer(
                "NotificationPreferencesUpdateResponse",
                NotificationPreferencesSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Update notification preferences (partial update allowed).",
    )
    def patch(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        ser = NotificationPreferencesSerializer(profile, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()

        return ok_response(
            ser.data,
            message="Notification preferences updated successfully.",
            status_code=status.HTTP_200_OK,
        )


    
