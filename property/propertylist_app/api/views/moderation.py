from datetime import timedelta

from django.utils import timezone
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.apps import apps
from django.db.models import Avg, Count, Max, Q, Sum
from django.conf import settings

from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError



from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer

from propertylist_app.services.captcha import verify_captcha
from propertylist_app.models import AuditLog, Report, Room, Booking, Payment, Message, MessageThread
from propertylist_app.api.permissions import IsModerationAdmin, IsOpsAdmin
from propertylist_app.api.pagination import StandardLimitOffsetPagination
from propertylist_app.api.throttling import ReportCreateScopedThrottle
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import standard_response_serializer
from propertylist_app.api.serializers import (
    ReportSerializer,
    OpsStatsResponseSerializer,
)


from .common import ok_response, error_response

class RoomModerationStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["active", "hidden"])


class RoomModerationStatusResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()







def _get_model(app_label: str, model_name: str):
    return apps.get_model(app_label, model_name)



class ReportCreateView(generics.CreateAPIView):
    """
    POST /api/reports/
    Body:
      {"target_type": "room"|"review"|"message"|"user", "object_id": 123, "reason": "abuse", "details": "â€¦"}
    """
    serializer_class = ReportSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReportCreateScopedThrottle]
    throttle_scope = "report-create"

    def perform_create(self, serializer):
        if settings.ENABLE_CAPTCHA:
            token = (self.request.data.get("captcha_token") or "").strip()
            if not verify_captcha(token, self.request.META.get("REMOTE_ADDR")):
                raise ValidationError({"captcha_token": "CAPTCHA verification failed."})

        report = serializer.save()

        try:
            AuditLog.objects.create(
                user=self.request.user,
                action="report.create",
                ip_address=getattr(self.request, "META", {}).get("REMOTE_ADDR"),
                extra_data={
                    "target_type": report.target_type,
                    "object_id": report.object_id,
                    "reason": report.reason,
                },
            )
        except Exception:
            pass



class ModerationReportListView(generics.ListAPIView):
    """GET /api/moderation/reports/?status=open|in_review|resolved|rejected â€” staff only."""
    serializer_class = ReportSerializer
    permission_classes = [IsModerationAdmin]
    pagination_class = StandardLimitOffsetPagination

    def get_queryset(self):
        status_q = self.request.query_params.get("status") or "open"
        qs = Report.objects.all().order_by("-created_at")
        if status_q in {"open", "in_review", "resolved", "rejected"}:
            qs = qs.filter(status=status_q)
        return qs



def _can_transition_report_status(current: str, new: str) -> bool:
    """
    Allowed transitions:
      open -> in_review/resolved/rejected
      in_review -> resolved/rejected
      resolved -> (terminal)
      rejected -> (terminal)
    Same-status "updates" are allowed (no-op).
    """
    if not current or not new:
        return False
    if current == new:
        return True

    allowed = {
        "open": {"in_review", "resolved", "rejected"},
        "in_review": {"resolved", "rejected"},
        "resolved": set(),
        "rejected": set(),
    }
    return new in allowed.get(current, set())

class ModerationReportUpdateView(generics.UpdateAPIView):
    """
    PATCH /api/moderation/reports/<id>/
    Body (any subset): {"status": "...", "resolution_notes": "...", "hide_room": true}
    """
    serializer_class = ReportSerializer
    permission_classes = [IsModerationAdmin]
    queryset = Report.objects.all()

    @extend_schema(
        request=ReportSerializer,
        responses={
            200: standard_response_serializer(
                "ModerationReportUpdateResponse",
                ReportSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def partial_update(self, request, *args, **kwargs):
        report = self.get_object()
        status_new = request.data.get("status")
        notes = request.data.get("resolution_notes", "")
        hide_room = bool(request.data.get("hide_room"))

        if status_new in {"in_review", "resolved", "rejected"}:
            if not _can_transition_report_status(report.status, status_new):
                return Response(
                    {
                        "ok": False,
                        "message": "Validation error.",
                        "errors": {
                            "status": [f"Invalid transition from '{report.status}' to '{status_new}'."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
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

        return ok_response(
            self.get_serializer(report).data,
            message="Moderation report updated successfully.",
            status_code=status.HTTP_200_OK,
        )




class ModerationReportModerateActionView(APIView):
    permission_classes = [IsModerationAdmin]

    @extend_schema(
        request=inline_serializer(
            name="ModerationReportModerateActionRequest",
            fields={
                "action": serializers.CharField(),
                "hide_room": serializers.BooleanField(required=False),
                "resolution_notes": serializers.CharField(required=False, allow_blank=True),
            },
        ),
        responses={
            200: inline_serializer(
                name="ModerationReportModerateActionOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="ModerationReportModerateActionData",
                        fields={
                            "id": serializers.IntegerField(),
                            "status": serializers.CharField(),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(description="Admin privileges required."),
            404: OpenApiResponse(description="Report not found."),
        },
        description="Moderate a report by changing its status, optionally hiding the reported room.",
    )
    def post(self, request, pk):
        """
        POST /api/v1/reports/<id>/moderate/
        body: {"action": "resolve"|"in_review"|"reject", "hide_room": true|false, "resolution_notes": "..." }
        """
        report = get_object_or_404(Report, pk=pk)

        action = (request.data.get("action") or "").strip().lower()
        notes = (request.data.get("resolution_notes") or "").strip()
        hide_room = bool(request.data.get("hide_room"))

        # map action â†’ status
        mapping = {
            "resolve": "resolved",
            "resolved": "resolved",
            "in_review": "in_review",
            "review": "in_review",
            "reject": "rejected",
            "rejected": "rejected",
        }
        new_status = mapping.get(action)
        if not new_status:
            return error_response(
                message="invalid action",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_action",
            )

        if not _can_transition_report_status(report.status, new_status):
            return Response(
                {"status": f"Invalid transition from '{report.status}' to '{new_status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # update report
        if notes:
            report.resolution_notes = notes
        report.status = new_status
        report.handled_by = request.user
        report.save(update_fields=["status", "resolution_notes", "handled_by", "updated_at"])

        # optional: hide the room if requested and target is a room
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
                action="report.moderate",
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                extra_data={"status": report.status, "report_id": report.pk},
            )
        except Exception:
            pass

        return ok_response(
            {"id": report.pk, "status": report.status},
            status_code=status.HTTP_200_OK,
        )




class RoomModerationStatusView(APIView):
    """
    PATCH /api/moderation/rooms/<id>/status/
    Body: {"status": "active"|"hidden"} â€” staff only.
    """
    permission_classes = [IsModerationAdmin]

    @extend_schema(
        request=RoomModerationStatusUpdateSerializer,
        responses={
            200: standard_response_serializer(
                "RoomModerationStatusUpdateResponse",
                RoomModerationStatusResponseSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def patch(self, request, pk):
        room = get_object_or_404(Room, pk=pk)

        serializer = RoomModerationStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        status_new = serializer.validated_data["status"]

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

        return ok_response(
            {"id": room.pk, "status": room.status},
            message="Room moderation status updated successfully.",
            status_code=status.HTTP_200_OK,
        )




class OpsStatsView(APIView):
    """
    GET /api/ops/stats/ â€” admin-only operational snapshot.
    Amounts reported in **GBP** (Payment.amount is stored in GBP).
    """
    permission_classes = [IsOpsAdmin]

    @extend_schema(
        responses={
            200: standard_response_serializer(
                "OpsStatsResponse",
                OpsStatsResponseSerializer,
            ),
        },
        description="Operational statistics for the platform."
    )
    def get(self, request):
        now = timezone.now()
        d7 = now - timedelta(days=7)
        d30 = now - timedelta(days=30)

        def _safe_count(qs):
            try:
                return int(qs.count())
            except Exception:
                return 0

        total_rooms = active_rooms = hidden_rooms = deleted_rooms = 0
        total_users = None
        bookings_7d = bookings_30d = upcoming_viewings = 0
        payments_30d_count = 0
        payments_30d_sum_gbp = 0.0
        messages_7d = threads_total = 0
        reports_open = reports_in_review = 0
        top_categories = []

        try:
            total_rooms = _safe_count(Room.objects.all())
            active_rooms = _safe_count(Room.objects.filter(status="active", is_deleted=False))
            hidden_rooms = _safe_count(Room.objects.filter(status="hidden", is_deleted=False))
            deleted_rooms = _safe_count(Room.objects.filter(is_deleted=True))

            try:
                total_users = int(get_user_model().objects.count())
            except Exception:
                total_users = None

            bookings_7d = _safe_count(Booking.objects.filter(created_at__gte=d7))
            bookings_30d = _safe_count(Booking.objects.filter(created_at__gte=d30))
            upcoming_viewings = _safe_count(Booking.objects.filter(start__gte=now, canceled_at__isnull=True))

            agg = Payment.objects.filter(status="succeeded", created_at__gte=d30).aggregate(
                sum_amt=Sum("amount"), cnt=Count("id")
            )
            payments_30d_count = int(agg.get("cnt") or 0)
            try:
                payments_30d_sum_gbp = round(float(agg.get("sum_amt") or 0), 2)
            except Exception:
                payments_30d_sum_gbp = 0.0

            messages_7d = _safe_count(Message.objects.filter(created__gte=d7))
            threads_total = _safe_count(MessageThread.objects.all())

            reports_open = _safe_count(Report.objects.filter(status="open"))
            reports_in_review = _safe_count(Report.objects.filter(status="in_review"))

            try:
                top_qs = (
                    Room.objects.filter(status="active", is_deleted=False)
                    .values("category__id", "category__name")
                    .annotate(cnt=Count("id"))
                    .order_by("-cnt")[:5]
                )
                top_categories = [
                    {
                        "id": r.get("category__id"),
                        "name": r.get("category__name"),
                        "count": int(r.get("cnt") or 0),
                    }
                    for r in top_qs
                ]
            except Exception:
                top_categories = []
        except Exception:
            pass

        data = {
            "listings": {
                "total": total_rooms,
                "active": active_rooms,
                "hidden": hidden_rooms,
                "deleted": deleted_rooms,
            },
            "users": {"total": total_users},
            "bookings": {
                "last_7_days": bookings_7d,
                "last_30_days": bookings_30d,
                "upcoming_viewings": upcoming_viewings,
            },
            "payments": {
                "last_30_days": {"count": payments_30d_count, "sum_gbp": payments_30d_sum_gbp}
            },
            "messages": {"last_7_days": messages_7d, "threads_total": threads_total},
            "reports": {"open": reports_open, "in_review": reports_in_review},
            "categories": {"top_active": top_categories},
        }

        return ok_response(
            data,
            message="Operational statistics retrieved successfully.",
            status_code=status.HTTP_200_OK,
        )



def _can_transition_report_status(current: str, new: str) -> bool:
    """
    Allowed transitions:
      open -> in_review/resolved/rejected
      in_review -> resolved/rejected
      resolved -> (terminal)
      rejected -> (terminal)
    Same-status "updates" are allowed (no-op).
    """
    if not current or not new:
        return False
    if current == new:
        return True

    allowed = {
        "open": {"in_review", "resolved", "rejected"},
        "in_review": {"resolved", "rejected"},
        "resolved": set(),
        "rejected": set(),
    }
    return new in allowed.get(current, set())






