from django.db import models
from django.db.models import Avg, Count
from django.utils import timezone

from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.exceptions import PermissionDenied

from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer, OpenApiParameter

from propertylist_app.models import Review, Tenancy
from propertylist_app.api.throttling import ReviewCreateThrottle, ReviewListThrottle
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import standard_response_serializer
from propertylist_app.api.serializers import (
    UserReviewListSerializer,
    UserReviewSummarySerializer,
    ReviewSerializer,
    ReviewCreateSerializer,
)
from .common import ok_response



class UserReviewSummaryView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
    responses={
            200: standard_response_serializer("UserReviewSummaryResponse", UserReviewSummarySerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        }
    )
    def get(self, request, user_id):
        revealed = Review.objects.filter(
            reviewee_id=user_id,
            active=True,
            reveal_at__isnull=False,
            reveal_at__lte=timezone.now(),
        )

        landlord_stats = revealed.filter(
            role=Review.ROLE_TENANT_TO_LANDLORD
        ).aggregate(
            landlord_count=Count("id"),
            landlord_average=Avg("overall_rating"),
        )

        tenant_stats = revealed.filter(
            role=Review.ROLE_LANDLORD_TO_TENANT
        ).aggregate(
            tenant_count=Count("id"),
            tenant_average=Avg("overall_rating"),
        )

        landlord_count = int(landlord_stats["landlord_count"] or 0)
        tenant_count = int(tenant_stats["tenant_count"] or 0)
        total_count = landlord_count + tenant_count

        landlord_avg = landlord_stats["landlord_average"]
        tenant_avg = tenant_stats["tenant_average"]

        overall_avg = None
        if total_count > 0:
            la = float(landlord_avg or 0)
            ta = float(tenant_avg or 0)
            overall_avg = ((la * landlord_count) + (ta * tenant_count)) / total_count

        data = {
            "landlord_count": landlord_count,
            "landlord_average": landlord_avg,
            "tenant_count": tenant_count,
            "tenant_average": tenant_avg,
            "total_reviews_count": total_count,
            "overall_rating_average": overall_avg,
        }

        serializer = UserReviewSummarySerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)
    


class ReviewCreateView(generics.CreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReviewCreateSerializer

    @extend_schema(
        request=ReviewCreateSerializer,
        responses={
            201: standard_response_serializer(
                "ReviewCreateResponse",
                ReviewSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        review = serializer.save()

        return ok_response(
            ReviewSerializer(review).data,
            message="Review created successfully.",
            status_code=status.HTTP_201_CREATED,
        )
    


class ReviewListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReviewSerializer

    def get_queryset(self):
        user = self.request.user
        now = timezone.now()
        return (
            Review.objects.select_related("reviewer", "reviewee", "tenancy")
            .filter(active=True)
            .filter(
                models.Q(reveal_at__lte=now)
                | models.Q(reviewer_id=user.id)
                | models.Q(reviewee_id=user.id)
            )
            .order_by("-submitted_at")
        )

    @extend_schema(
        responses={
            200: inline_serializer(
                name="PaginatedReviewListOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "data": ReviewSerializer(many=True),
                    "meta": inline_serializer(
                        name="ReviewListMeta",
                        fields={
                            "count": serializers.IntegerField(),
                            "next": serializers.CharField(allow_null=True),
                            "previous": serializers.CharField(allow_null=True),
                        },
                    ),
                },
            )
        },
        parameters=[
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of reviews to return.",
            ),
            OpenApiParameter(
                name="offset",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of reviews to skip before starting the result set.",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Ordering field.",
            ),
        ],
        description="List reviews for the authenticated user. Returns an ok_response envelope with pagination metadata.",
    )
    def list(self, request, *args, **kwargs):
        resp = super().list(request, *args, **kwargs)

        # Convert DRF pagination shape -> ok_response(meta=...)
        if isinstance(resp.data, dict) and "results" in resp.data:
            meta = {
                "count": resp.data.get("count"),
                "next": resp.data.get("next"),
                "previous": resp.data.get("previous"),
            }
            return ok_response(resp.data.get("results"), meta=meta, status_code=resp.status_code)

        return ok_response(resp.data, status_code=resp.status_code)   
      
      
      
      
class ReviewDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReviewSerializer
    queryset = Review.objects.select_related("reviewer", "reviewee", "tenancy").filter(active=True)

    def get_object(self):
        obj = super().get_object()
        user = self.request.user
        now = timezone.now()

        is_visible = (
            (obj.reveal_at and obj.reveal_at <= now) or
            (obj.reviewer_id == user.id) or
            (obj.reviewee_id == user.id)
        )
        if not is_visible:
            raise PermissionDenied("You do not have permission to view this review yet.")
        return obj


  

class TenancyReviewListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses={
            200: inline_serializer(
                name="TenancyReviewListResponse",
                fields={
                    "my_review": UserReviewListSerializer(allow_null=True),
                    "other_review": UserReviewListSerializer(allow_null=True),
                    "other_review_reveal_at": serializers.DateTimeField(allow_null=True),
                },
            ),
            403: inline_serializer(
                name="TenancyReviewListForbiddenResponse",
                fields={
                    "detail": serializers.CharField(),
                },
            ),
            404: inline_serializer(
                name="TenancyReviewListNotFoundResponse",
                fields={
                    "detail": serializers.CharField(),
                },
            ),
        },
        description="Return the authenticated user's review and the counterparty review for a tenancy, if visible.",
    )
    def get(self, request, tenancy_id):
        user = request.user
        try:
            tenancy = Tenancy.objects.select_related("room", "tenant", "landlord").get(id=tenancy_id)
        except Tenancy.DoesNotExist:
            return Response({"detail": "Tenancy not found."}, status=status.HTTP_404_NOT_FOUND)

        if user.id not in {tenancy.tenant_id, tenancy.landlord_id}:
            return Response(
                {"detail": "You are not allowed to view these reviews."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if user.id == tenancy.tenant_id:
            my_role = Review.ROLE_TENANT_TO_LANDLORD
            other_role = Review.ROLE_LANDLORD_TO_TENANT
        else:
            my_role = Review.ROLE_LANDLORD_TO_TENANT
            other_role = Review.ROLE_TENANT_TO_LANDLORD

        my_review = Review.objects.filter(tenancy=tenancy, role=my_role, active=True).first()
        other_review = Review.objects.filter(tenancy=tenancy, role=other_role, active=True).first()

        now = timezone.now()

        my_review_data = (
            UserReviewListSerializer(my_review, context={"request": request}).data
            if my_review else None
        )

        if other_review and other_review.reveal_at:
            other_reveal_at = other_review.reveal_at
        else:
            other_reveal_at = tenancy.review_open_at

        other_visible = bool(other_review and other_reveal_at and now >= other_reveal_at)

        other_review_data = (
            UserReviewListSerializer(other_review, context={"request": request}).data
            if other_visible else None
        )

        return Response(
            {
                "my_review": my_review_data,
                "other_review": other_review_data,
                "other_review_reveal_at": other_reveal_at,
            },
            status=status.HTTP_200_OK,
        )




class UserReviewsView(ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = UserReviewListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Review.objects.none()
        user_id = self.kwargs["user_id"]
        for_param = self.request.query_params.get("for")

        qs = Review.objects.filter(
            reviewee_id=user_id,
            reveal_at__isnull=False,
            reveal_at__lte=timezone.now(),
            active=True,
        ).order_by("-submitted_at")

        if for_param == "landlord":
            return qs.filter(role=Review.ROLE_TENANT_TO_LANDLORD)

        if for_param == "tenant":
            return qs.filter(role=Review.ROLE_LANDLORD_TO_TENANT)

        # if not provided or invalid, return nothing to avoid leaking mixed data accidentally
        return qs.none()



class TenancyReviewCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=ReviewCreateSerializer,
        responses={
            201: inline_serializer(
                name="TenancyReviewCreateOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": ReviewSerializer(),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Tenancy not found."),
        },
        description="Create a tenancy review and return it in ok_response envelope.",
    )
    def post(self, request, tenancy_id):
        serializer = ReviewCreateSerializer(
            data={**request.data, "tenancy_id": tenancy_id},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        review = serializer.save()

        return ok_response(
            ReviewSerializer(review).data,
            message="Review submitted successfully.",
            status_code=status.HTTP_201_CREATED,
        )
       
