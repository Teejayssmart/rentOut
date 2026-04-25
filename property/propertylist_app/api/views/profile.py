from datetime import timedelta



from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser



from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.conf import settings
from django.db.models import Avg
from django.utils import timezone


from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer

from propertylist_app.models import UserProfile,Review
from propertylist_app.api.serializers import (
    UserSerializer,
    UserProfileSerializer,
    DetailResponseSerializer,
    AccountDeleteRequestSerializer,
    AccountDeleteCancelSerializer,
    OnboardingCompleteSerializer,
    ProfilePageSerializer,
    AvatarUploadRequestSerializer,
    AvatarUploadResponseSerializer,
    ChangeEmailRequestSerializer,
    ChangePasswordRequestSerializer,
    UserSerializer,
    UserProfileSerializer,
    ReviewSerializer,
)
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import standard_response_serializer
from propertylist_app.validators import validate_avatar_image

from .common import ok_response






class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        # Always ensure the profile exists
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return profile

    @extend_schema(
        request=UserProfileSerializer,
        responses={
            200: standard_response_serializer(
                "UserProfileUpdateResponse",
                UserProfileSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return ok_response(
            serializer.data,
            message="Profile updated successfully.",
            status_code=status.HTTP_200_OK,
        )



class OnboardingCompleteView(APIView):
    """
    Marks onboarding as completed for the logged-in user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=OnboardingCompleteSerializer,
        responses={
            200: inline_serializer(
                name="OnboardingCompleteOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="OnboardingCompleteData",
                        fields={
                            "onboarding_completed": serializers.BooleanField(),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Mark onboarding as completed for the current user. Returns ok_response envelope.",
    )
    def post(self, request):
        serializer = OnboardingCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile = request.user.profile
        profile.onboarding_completed = True
        profile.save(update_fields=["onboarding_completed"])

        return ok_response(
            {"onboarding_completed": True},
            status_code=status.HTTP_200_OK,
        )
        
        
        
class MyProfilePageView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: standard_response_serializer(
                "MyProfilePageResponse",
                ProfilePageSerializer,
            ),
            401: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def get(self, request):
        user = request.user
        profile, _ = UserProfile.objects.get_or_create(user=user)

        qs = Review.objects.filter(
            reviewee_id=user.id,
            reveal_at__isnull=False,
            reveal_at__lte=timezone.now(),
            active=True,
        )

        landlord_qs = qs.filter(role=Review.ROLE_TENANT_TO_LANDLORD)
        tenant_qs = qs.filter(role=Review.ROLE_LANDLORD_TO_TENANT)

        landlord_count = landlord_qs.count()
        tenant_count = tenant_qs.count()

        landlord_avg = landlord_qs.aggregate(a=Avg("overall_rating")).get("a")
        tenant_avg = tenant_qs.aggregate(a=Avg("overall_rating")).get("a")

        total = landlord_count + tenant_count

        overall = None
        if total > 0:
            la = float(landlord_avg or 0)
            ta = float(tenant_avg or 0)
            overall = ((la * landlord_count) + (ta * tenant_count)) / total

        preview_qs = qs.order_by("-submitted_at")[:2]
        preview = ReviewSerializer(preview_qs, many=True, context={"request": request}).data

        age = None
        if profile.date_of_birth:
            today = timezone.now().date()
            dob = profile.date_of_birth
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

        location = (profile.address_manual or "").strip()
        if not location:
            location = (profile.postcode or "").strip()

        payload = {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "date_joined": user.date_joined,
            "avatar": (profile.avatar.url if profile.avatar else None),
            "role": profile.role,
            "gender": profile.get_gender_display() if profile.gender else "",
            "occupation": profile.occupation or "",
            "postcode": profile.postcode or "",
            "address_manual": profile.address_manual or "",
            "date_of_birth": profile.date_of_birth,
            "about_you": profile.about_you or "",
            "age": age,
            "location": location,
            "total_reviews": total,
            "overall_rating": overall,
            "landlord_reviews_count": landlord_count,
            "landlord_rating_average": landlord_avg,
            "tenant_reviews_count": tenant_count,
            "tenant_rating_average": tenant_avg,
            "reviews_preview": preview,
        }

        ser = ProfilePageSerializer(payload, context={"request": request})
        return ok_response(
            ser.data,
            message="Profile page retrieved successfully.",
            status_code=status.HTTP_200_OK,
        )
        

class UserAvatarUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        request={"multipart/form-data": AvatarUploadRequestSerializer},
        responses={
            200: inline_serializer(
                name="AvatarUploadOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": AvatarUploadResponseSerializer(),
                },
            ),
            400: OpenApiResponse(description="Invalid file or validation error."),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Upload/update the current user's avatar.",
    )
    def post(self, request):
        # Ensure a profile exists (prevents 500 if none)
        profile, _ = UserProfile.objects.get_or_create(user=request.user)

        file_obj = request.FILES.get("avatar")
        if not file_obj:
            return Response(
                {"avatar": "File is required (form-data key 'avatar')."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Our validator raises DjangoValidationError; convert to a 400 API response
        try:
            cleaned = validate_avatar_image(file_obj)
        except DjangoValidationError as e:
            # normalize error payload for tests
            msg = "; ".join([str(m) for m in (e.messages if hasattr(e, "messages") else [str(e)])])
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        profile.avatar = cleaned
        profile.save(update_fields=["avatar"])

        payload = {
            "ok": True,
            "message": None,
            "data": {
                "avatar": profile.avatar.url if profile.avatar else None,
            },
        }
        return Response(payload, status=status.HTTP_200_OK)



class ChangeEmailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ChangeEmailRequestSerializer,
        responses={
            200: inline_serializer(
                name="ChangeEmailOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="ChangeEmailData",
                        fields={
                            "detail": serializers.CharField(),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Change the user's email address.",
    )
    def post(self, request):
        ser = ChangeEmailRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        current_password = ser.validated_data["current_password"]
        new_email = ser.validated_data["new_email"]

        user = authenticate(request, username=request.user.username, password=current_password)
        if not user:
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if get_user_model().objects.filter(email__iexact=new_email).exclude(pk=request.user.pk).exists():
            return Response(
                {"new_email": "This email is already in use."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.email = new_email
        user.save(update_fields=["email"])

        return ok_response(
            {"detail": "Email updated."},
            status_code=status.HTTP_200_OK,
        )
    
class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ChangePasswordRequestSerializer,
        responses={
            200: inline_serializer(
                name="ChangePasswordOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="ChangePasswordData",
                        fields={
                            "detail": serializers.CharField(),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Change the current user's password.",
    )
    def post(self, request):
        ser = ChangePasswordRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        current_password = ser.validated_data["current_password"]
        new_password = ser.validated_data["new_password"]
        confirm_password = ser.validated_data["confirm_password"]

        if new_password != confirm_password:
            return Response(
                {"confirm_password": "Passwords do not match."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=request.user.username, password=current_password)
        if not user:
            return Response(
                {"current_password": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as e:
            return Response(
                {"new_password": list(e.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])

        return ok_response(
            {"detail": "Password updated. Please log in again."},
            status_code=status.HTTP_200_OK,
        )

class DeactivateAccountView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="DeactivateAccountOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="DeactivateAccountData",
                        fields={
                            "detail": serializers.CharField(),
                        },
                    ),
                },
            ),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Deactivate the current user's account.",
    )
    def post(self, request):
        request.user.is_active = False
        request.user.save(update_fields=["is_active"])

        return ok_response(
            {"detail": "Account deactivated."},
            status_code=status.HTTP_200_OK,
        )



class DeleteAccountRequestView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=AccountDeleteRequestSerializer,
        responses={
            200: inline_serializer(
                name="DeleteAccountRequestOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="DeleteAccountRequestData",
                        fields={
                            "detail": serializers.CharField(),
                            "scheduled_for": serializers.DateTimeField(),
                            "grace_days": serializers.IntegerField(),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Schedule the current user's account for deletion after the grace period.",
    )
    def post(self, request):
        from propertylist_app.models import UserProfile

        ser = AccountDeleteRequestSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)

        grace_days = getattr(settings, "ACCOUNT_DELETION_GRACE_DAYS", 7)
        now = timezone.now()
        scheduled_for = now + timedelta(days=int(grace_days))

        # lock account immediately
        request.user.is_active = False
        request.user.save(update_fields=["is_active"])

        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.pending_deletion_requested_at = now
        profile.pending_deletion_scheduled_for = scheduled_for
        profile.save(update_fields=["pending_deletion_requested_at", "pending_deletion_scheduled_for"])

        return ok_response(
            {
                "detail": "Account scheduled for deletion.",
                "scheduled_for": scheduled_for,
                "grace_days": int(grace_days),
            },
            status_code=status.HTTP_200_OK,
        )
        
        
class DeleteAccountCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=AccountDeleteCancelSerializer,
        responses={
            200: inline_serializer(
                name="DeleteAccountCancelOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="DeleteAccountCancelData",
                        fields={
                            "detail": serializers.CharField(),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Cancel a pending account deletion request.",
    )
    def post(self, request):
        from propertylist_app.models import UserProfile

        ser = AccountDeleteCancelSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        profile, _ = UserProfile.objects.get_or_create(user=request.user)

        # if nothing pending, return 200 (idempotent)
        profile.pending_deletion_requested_at = None
        profile.pending_deletion_scheduled_for = None
        profile.save(update_fields=["pending_deletion_requested_at", "pending_deletion_scheduled_for"])

        request.user.is_active = True
        request.user.save(update_fields=["is_active"])

        return ok_response(
            {"detail": "Account deletion cancelled."},
            status_code=status.HTTP_200_OK,
        )



         
