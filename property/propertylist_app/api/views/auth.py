#Standard/library
from datetime import datetime, timezone as dt_timezone
import logging
import jwt
from jwt import PyJWKClient
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests



#Django
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model

from django.core import mail
from django.core.cache import cache
from django.utils.crypto import get_random_string
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt


#DRF / SimpleJWT / spectacular
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer as SimpleJWTTokenRefreshSerializer

from drf_spectacular.utils import (
    extend_schema,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)



#Project helpers/services
from propertylist_app.services.captcha import verify_captcha
from propertylist_app.services.security import (
    clear_login_failures,
    is_locked_out,
    register_login_failure,
)
from propertylist_app.validators import ensure_idempotency
from propertylist_app.api.throttling import (
    LoginScopedThrottle,
    PasswordResetScopedThrottle,
    PasswordResetConfirmScopedThrottle,
    RegisterAnonThrottle,
    RegisterScopedThrottle,
)
from propertylist_app.api.schema_serializers import (
    ErrorResponseSerializer,
)
from propertylist_app.api import views as views_mod
from propertylist_app.api.schema_helpers import (
    standard_response_serializer,
)
from .common import ok_response, error_response


#Project serializers/models
from propertylist_app.models import EmailOTP, IdempotencyKey, UserProfile
from propertylist_app.api.serializers import (
    LoginResponseSerializer,
    TokenRefreshRequestSerializer,
    DetailResponseSerializer,
)

from ..serializers import (
    RegistrationSerializer,
    LoginSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    EmailOTPVerifySerializer,
    EmailOTPResendSerializer,
    UserSerializer,
    UserProfileSerializer,
    CreatePasswordRequestSerializer,
)


#Logger
logger_auth = logging.getLogger("rentout.auth")
logger = logger_auth

#DRF throttling
from rest_framework.throttling import ScopedRateThrottle

from .common import error_response




class TokenRefreshEnvelopeView(TokenRefreshView):
    """
    Wrap SimpleJWT refresh response in the API success envelope.
    """

    @extend_schema(
        request=inline_serializer(
            name="TokenRefreshEnvelopeRequest",
            fields={
                "refresh": serializers.CharField(),
            },
        ),
        responses={
            200: inline_serializer(
                name="TokenRefreshEnvelopeOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "data": inline_serializer(
                        name="TokenRefreshEnvelopeData",
                        fields={
                            "access": serializers.CharField(),
                            "refresh": serializers.CharField(required=False),
                            "access_expires_at": serializers.CharField(required=False),
                            "refresh_expires_at": serializers.CharField(required=False),
                        },
                    ),
                },
            ),
            400: DetailResponseSerializer,
            401: DetailResponseSerializer,
        },
        auth=[],
        description="Refresh JWT access token and return it in the API success envelope.",
    )
    def post(self, request):
        ser = TokenRefreshRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        refresh_str = (ser.validated_data.get("refresh") or "").strip()
        if not refresh_str:
            raise ValidationError({"refresh": "Refresh token is required."})

        jwt_ser = SimpleJWTTokenRefreshSerializer(data={"refresh": refresh_str})
        try:
            jwt_ser.is_valid(raise_exception=True)
        except Exception:
            raise ValidationError({"refresh": "Invalid or expired refresh token."})

        payload = jwt_ser.validated_data

        try:
            access_token = AccessToken(payload["access"])
            access_exp = datetime.fromtimestamp(int(access_token["exp"]), tz=dt_timezone.utc)
        except Exception:
            raise ValidationError({"detail": "Unable to determine access token expiry."})

        data = {
            "access": payload["access"],
            "access_expires_at": access_exp,
        }

        if "refresh" in payload:
            try:
                rotated_refresh = RefreshToken(payload["refresh"])
                refresh_exp = datetime.fromtimestamp(int(rotated_refresh["exp"]), tz=dt_timezone.utc)
                data["refresh"] = payload["refresh"]
                data["refresh_expires_at"] = refresh_exp
            except Exception:
                raise ValidationError({"detail": "Unable to determine refresh token expiry."})
        else:
            try:
                original_refresh = RefreshToken(refresh_str)
                refresh_exp = datetime.fromtimestamp(int(original_refresh["exp"]), tz=dt_timezone.utc)
                data["refresh_expires_at"] = refresh_exp
            except Exception:
                raise ValidationError({"detail": "Unable to determine refresh token expiry."})

        return ok_response(
            data,
            status_code=status.HTTP_200_OK,
        )










APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"


def _verify_apple_identity_token(raw_token: str) -> dict:
    """
    Verify an Apple identity token (JWT) using Apple's JWKS.
    """
    audience = getattr(settings, "APPLE_AUDIENCE", "").strip()
    if not audience:
        raise ValueError("APPLE_AUDIENCE is not configured.")

    if not raw_token:
        raise ValueError("Missing Apple identity token.")

    jwk_client = PyJWKClient(APPLE_JWKS_URL)
    signing_key = jwk_client.get_signing_key_from_jwt(raw_token)

    payload = jwt.decode(
        raw_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        issuer=APPLE_ISSUER,
    )

    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise ValueError("Apple token does not include an email address.")

    email_verified = payload.get("email_verified", False)
    if isinstance(email_verified, str):
        email_verified = email_verified.lower() == "true"

    if not email_verified:
        raise ValueError("Apple account email is not verified.")

    return payload




def mark_profile_email_verified(user) -> UserProfile:
    """
    Ensure the user's profile exists and mark its email as verified.

    Reason:
    The main login flow checks user.profile.email_verified, so all auth
    entry points should update the same source of truth.
    """
    profile, _ = UserProfile.objects.get_or_create(user=user)

    fields_to_update = []

    if not profile.email_verified:
        profile.email_verified = True
        fields_to_update.append("email_verified")

    if profile.email_verified_at is None:
        profile.email_verified_at = timezone.now()
        fields_to_update.append("email_verified_at")

    if fields_to_update:
        profile.save(update_fields=fields_to_update)

    return profile


def generate_unique_username_from_email(email: str) -> str:
    """
    Build a unique username from the email local part.

    Reason:
    Social auth currently uses email.split("@")[0], which can collide
    across providers or users with the same local part.
    """
    UserModel = get_user_model()

    base = (email.split("@")[0] or "user").strip().lower()
    base = "".join(ch for ch in base if ch.isalnum() or ch == "_")
    if not base:
        base = "user"

    candidate = base
    counter = 1

    while UserModel.objects.filter(username=candidate).exists():
        counter += 1
        candidate = f"{base}{counter}"

    return candidate



class RegistrationView(generics.CreateAPIView):
    serializer_class = RegistrationSerializer
    permission_classes = [AllowAny]
    throttle_classes = [RegisterAnonThrottle]
    versioning_class = None

    @extend_schema(
        request=RegistrationSerializer,
        responses={
            201: standard_response_serializer(
                "RegistrationResponse",
                RegistrationSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def create(self, request, *args, **kwargs):
        # Optional CAPTCHA
        if getattr(settings, "ENABLE_CAPTCHA", False):
            token = (request.data.get("captcha_token") or "").strip()
            if not views_mod.verify_captcha(token, request.META.get("REMOTE_ADDR", "")):
                return error_response(
                    message="CAPTCHA verification failed.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    code="bad_request",
                )

        # 1) Terms & Privacy must be accepted
        raw_terms = request.data.get("terms_accepted")
        if raw_terms not in [True, "true", "True", "1", 1, "on"]:
            return error_response(
                message="Invalid input.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="validation_error",
                field_errors={
                    "terms_accepted": ["You must accept Terms & Privacy."]
                },
                details={
                    "terms_accepted": ["You must accept Terms & Privacy."]
                },
            )

        # 2) Duplicate email must give 400
        email = (request.data.get("email") or "").strip()
        if email and get_user_model().objects.filter(email__iexact=email).exists():
           return error_response(
                message="Invalid input.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="validation_error",
                field_errors={
                    "email": ["This email is already in use."]
                },
                details={
                    "email": ["This email is already in use."]
                },
            )
        # 3) Let the serializer do the rest
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return ok_response(
            serializer.data,
            message="Registration successful.",
            status_code=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_exempt, name="dispatch")
class GoogleRegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [RegisterAnonThrottle]

    @extend_schema(
        request=inline_serializer(
            name="GoogleRegisterRequest",
            fields={
                "token": serializers.CharField(),
            },
        ),
        responses={
            200: inline_serializer(
                name="GoogleRegisterResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(),
                    "data": inline_serializer(
                        name="GoogleRegisterData",
                        fields={
                            "refresh": serializers.CharField(),
                            "access": serializers.CharField(),
                        },
                    ),
                },
            ),
            400: inline_serializer(
                name="GoogleRegisterBadRequestResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(),
                    "data": serializers.JSONField(allow_null=True),
                },
            ),
            429: OpenApiResponse(description="Rate limit exceeded."),
        },
        auth=[],
        description="Register or log in with a Google ID token. Returns JWT refresh and access tokens.",
    )
    def post(self, request, *args, **kwargs):
        token = request.data.get("token")

        if not token:
            return error_response(
                message="Missing token",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="bad_request",
            )

        try:
            idinfo = views_mod.id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                settings.GOOGLE_WEB_CLIENT_ID,
            )
        except Exception:
            return error_response(
                message="Invalid Google token",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_token",
            )

        email = idinfo.get("email")
        if not email:
            return error_response(
                message="Email not provided",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="bad_request",
            )

        User = get_user_model()

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": generate_unique_username_from_email(email),
            },
        )

        # Keep social auth consistent with the main login flow,
        # which checks user.profile.email_verified
        mark_profile_email_verified(user)

        refresh = RefreshToken.for_user(user)

        return ok_response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
            message="Login successful",
            status_code=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name="dispatch")
class AppleRegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [RegisterAnonThrottle]
    versioning_class = None

    @extend_schema(
        request=inline_serializer(
            name="AppleRegisterRequest",
            fields={
                "identity_token": serializers.CharField(),
            },
        ),
        responses={
            200: inline_serializer(
                name="AppleRegisterResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(),
                    "data": inline_serializer(
                        name="AppleRegisterData",
                        fields={
                            "refresh": serializers.CharField(),
                            "access": serializers.CharField(),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description="Missing or invalid Apple identity token."),
        },
        auth=[],
        description="Register or log in with an Apple identity token. Returns JWT refresh and access tokens.",
    )
    def post(self, request, *args, **kwargs):
        identity_token = (request.data.get("identity_token") or "").strip()

        if not identity_token:
            return error_response(
                message="Missing identity_token",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="bad_request",
            )

        try:
            payload = views_mod._verify_apple_identity_token(identity_token)
        except ValueError as exc:
            return error_response(
                message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
                code="bad_request",
            )
        except Exception:
            return error_response(
                message="Invalid Apple identity token",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_token",
            )

        email = payload.get("email", "").strip().lower()

        User = get_user_model()
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": generate_unique_username_from_email(email),
            },
        )

        # Keep social auth consistent with the main login flow,
        # which checks user.profile.email_verified
        mark_profile_email_verified(user)

        refresh = RefreshToken.for_user(user)

        return ok_response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
            message="Login successful",
            status_code=status.HTTP_200_OK,
        )




class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "login"
    versioning_class = None
    throttle_classes = [ScopedRateThrottle]

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: inline_serializer(
                name="LoginOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="LoginOkData",
                        fields={
                            "tokens": inline_serializer(
                                name="LoginTokenData",
                                fields={
                                    "access": serializers.CharField(),
                                    "refresh": serializers.CharField(),
                                    "access_expires_at": serializers.DateTimeField(),
                                    "refresh_expires_at": serializers.DateTimeField(),
                                },
                            ),
                            "user": UserSerializer(),
                            "profile": UserProfileSerializer(),
                        },
                    ),
                },
            ),
            400: DetailResponseSerializer,
            403: DetailResponseSerializer,
            429: DetailResponseSerializer,
        },
        auth=[],
        description=(
            "Login using either email or username in 'identifier'. "
            "Returns JWT refresh/access tokens on success."
        ),
    )
    def post(self, request, *args, **kwargs):


        try:
            data = request.data.copy()

            if "identifier" not in data:
                if "username" in data:
                    data["identifier"] = data.get("username")
                elif "email" in data:
                    data["identifier"] = data.get("email")

            identifier_for_lock = (data.get("identifier") or "").strip()
            ip = request.META.get("REMOTE_ADDR", "") or ""

            logger.info("login_attempt ip=%s identifier=%s", ip, (identifier_for_lock or "-"))

            if identifier_for_lock and is_locked_out(ip, identifier_for_lock):
                logger.warning("login_lockout ip=%s identifier=%s", ip, identifier_for_lock)
                return error_response(
                    message="Too many failed attempts. Try again later.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    code="lockout",
                )

            if getattr(settings, "ENABLE_CAPTCHA", False):
                token = (data.get("captcha_token") or "").strip()
                if not views_mod.verify_captcha(token, ip):
                    logger.warning("login_captcha_failed ip=%s identifier=%s", ip, (identifier_for_lock or "-"))
                    return error_response(
                        message="CAPTCHA verification failed.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )

            ser = LoginSerializer(data=data)
            ser.is_valid(raise_exception=True)

            identifier = ser.validated_data["identifier"]
            password = ser.validated_data["password"]

            lookup_username = identifier
            if "@" in identifier:
                try:
                    u = get_user_model().objects.get(email__iexact=identifier)
                    lookup_username = u.username
                except get_user_model().DoesNotExist:
                    pass

            user = authenticate(request, username=lookup_username, password=password)
            if user:
                profile = None
                if hasattr(user, "profile"):
                    try:
                        profile = user.profile
                    except Exception:
                        profile = None

                if not profile or not getattr(profile, "email_verified", False):
                    logger.warning("login_email_not_verified ip=%s user_id=%s", ip, user.id)
                    return error_response(
                        message="Please verify your email with the 6-digit code we sent.",
                        status_code=status.HTTP_403_FORBIDDEN,
                    )

                clear_login_failures(ip, identifier_for_lock or identifier)

                profile, _ = UserProfile.objects.get_or_create(user=user)

                refresh = RefreshToken.for_user(user)
                access_token = refresh.access_token

                access_exp = datetime.fromtimestamp(int(access_token["exp"]), tz=dt_timezone.utc)
                refresh_exp = datetime.fromtimestamp(int(refresh["exp"]), tz=dt_timezone.utc)

                payload = {
                    "tokens": {
                        "access": str(access_token),
                        "refresh": str(refresh),
                        "access_expires_at": access_exp,
                        "refresh_expires_at": refresh_exp,
                    },
                    "user": UserSerializer(user).data,
                    "profile": UserProfileSerializer(profile).data,
                }

                logger.info("login_success ip=%s user_id=%s", ip, user.id)
                return ok_response(payload, status_code=status.HTTP_200_OK)

            register_login_failure(ip, identifier_for_lock or identifier)

            if identifier_for_lock and is_locked_out(ip, identifier_for_lock):
                logger.warning("login_lockout ip=%s identifier=%s", ip, identifier_for_lock)
                return error_response(
                    message="Too many failed attempts. Try again later.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    code="lockout",
                )

            logger.warning("login_invalid_credentials ip=%s identifier=%s", ip, (identifier_for_lock or identifier))
            return error_response(
                message="Invalid credentials.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        except Exception:
            logger.exception("LoginView crashed")
            raise



class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    versioning_class = None

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="LogoutOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="LogoutData",
                        fields={"detail": serializers.CharField()},
                    ),
                },
            ),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Logout current user. Returns ok_response envelope.",
    )
    def post(self, request):
        refresh = (request.data.get("refresh") or "").strip()
        if not refresh:
            # Reason: allow global error handler to format consistently
            raise ValidationError({"refresh": "Refresh token is required."})

        try:
            RefreshToken(refresh).blacklist()
        except Exception:
            # Reason: treat invalid/expired/already-blacklisted the same for security + consistency
            raise ValidationError({"refresh": "Invalid or expired refresh token."})

        # Reason: A3/C1 consistent success envelope
        return ok_response({"detail": "Logged out."}, status_code=status.HTTP_200_OK)


class TokenRefreshView(APIView):
    permission_classes = [AllowAny]
    versioning_class = None

    @extend_schema(
        request=TokenRefreshRequestSerializer,
        responses={
            200: inline_serializer(
                name="TokenRefreshOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="TokenRefreshData",
                        fields={
                            "access": serializers.CharField(),
                            "access_expires_at": serializers.DateTimeField(),
                            "refresh_expires_at": serializers.DateTimeField(),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description="Invalid or expired refresh token."),
        },
        auth=[],
        description="Exchange a refresh token for a new access token. Returns ok_response envelope.",
    )
    def post(self, request):
        from propertylist_app.api.serializers import TokenRefreshRequestSerializer

        ser = TokenRefreshRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        refresh_str = (ser.validated_data.get("refresh") or "").strip()
        if not refresh_str:
            raise ValidationError({"refresh": "Refresh token is required."})

        try:
            refresh = RefreshToken(refresh_str)
            access_token = refresh.access_token

            access_exp = datetime.fromtimestamp(int(access_token["exp"]), tz=dt_timezone.utc)
            refresh_exp = datetime.fromtimestamp(int(refresh["exp"]), tz=dt_timezone.utc)

            payload = {
                "access": str(access_token),
                "access_expires_at": access_exp,
                "refresh_expires_at": refresh_exp,
            }

            return ok_response(payload, status_code=status.HTTP_200_OK)

        except Exception:
            raise ValidationError({"refresh": "Invalid or expired refresh token."})


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetScopedThrottle]
    versioning_class = None

    @extend_schema(
        request=PasswordResetRequestSerializer,
        responses={
            200: inline_serializer(
                name="PasswordResetRequestOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="PasswordResetRequestData",
                        fields={
                            "detail": serializers.CharField(),
                            "token": serializers.CharField(required=False, allow_null=True),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            429: OpenApiResponse(description="Rate limit exceeded."),
        },
        auth=[],
        description="Request a password reset email. Returns ok_response envelope.",
    )
    def post(self, request):
        if settings.ENABLE_CAPTCHA:
            token = (request.data.get("captcha_token") or "").strip()
            if not views_mod.verify_captcha(token, request.META.get("REMOTE_ADDR")):
                return error_response(
                    message="CAPTCHA verification failed.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        ser = PasswordResetRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        email = ser.validated_data["email"].strip()
        UserModel = get_user_model()

        # Always return a generic response (donâ€™t reveal if email exists)
        generic_response = ok_response(
            {"detail": "If that email exists, a reset code has been sent."},
            status_code=status.HTTP_200_OK,
        )

        try:
            user = UserModel.objects.get(email__iexact=email)
        except UserModel.DoesNotExist:
            return generic_response

        cache_key = f"password_reset_otp_resend_{user.id}"
        if cache.get(cache_key):
            return generic_response
        cache.set(cache_key, 1, timeout=60)

        # Invalidate previous unused OTPs
        EmailOTP.objects.filter(
            user=user,
            purpose=EmailOTP.PURPOSE_PASSWORD_RESET,
            used_at__isnull=True,
        ).update(used_at=timezone.now())

        # Create a fresh 6-digit code
        code = get_random_string(6, allowed_chars="0123456789")
        EmailOTP.create_for(
            user,
            code,
            ttl_minutes=settings.OTP_EXPIRY_MINUTES,
            purpose=EmailOTP.PURPOSE_PASSWORD_RESET,
        )

        # Send email (locmem backend in tests will capture this)
        mail.send_mail(
            subject="Reset your password (RentOut)",
            message=f"Your password reset code is: {code}",
            from_email=None,
            recipient_list=[user.email],
            fail_silently=True,
        )

        # Important for tests/dev: return token so tests can use it easily.
        if settings.DEBUG:
            return ok_response(
                {"detail": "Reset code sent.", "token": code},
                status_code=status.HTTP_200_OK,
            )

        return generic_response


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetConfirmScopedThrottle]
    versioning_class = None

    @extend_schema(
        request=PasswordResetConfirmSerializer,
        responses={
            200: inline_serializer(
                name="PasswordResetConfirmOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="PasswordResetConfirmData",
                        fields={"detail": serializers.CharField()},
                    ),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            429: OpenApiResponse(description="Rate limit exceeded."),
        },
        auth=[],
        description="Confirm a password reset using email, token, and new password. Returns ok_response envelope.",
    )
    def post(self, request):
        ser = PasswordResetConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        email = ser.validated_data["email"].strip()
        token = (ser.validated_data["token"] or "").strip()
        new_password = ser.validated_data["new_password"]

        UserModel = get_user_model()
        try:
            user = UserModel.objects.get(email__iexact=email)
        except UserModel.DoesNotExist:
            return error_response(
                message="Invalid token.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_token",
            )


        otp = (
            EmailOTP.objects.filter(
                user=user,
                purpose=EmailOTP.PURPOSE_PASSWORD_RESET,
                used_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )

        if not otp:
            return error_response(
                    message="Invalid token.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    code="invalid_token",
                )

        if otp.is_expired:
            return error_response(
                message="Token expired.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="token_expired",
            )

        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            return error_response(
                message="Too many attempts. Request a new reset code.",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                code="rate_limited",
            )
        if not otp.matches(token):
            otp.attempts = int(otp.attempts or 0) + 1
            otp.save(update_fields=["attempts"])
            return error_response(
                message="Invalid token.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_token",
            )

        # Token is valid: mark used + set new password
        otp.mark_used()
        user.set_password(new_password)
        user.save(update_fields=["password"])

        return ok_response(
            {"detail": "Password has been reset."},
            status_code=status.HTTP_200_OK,
        )


class CreatePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CreatePasswordRequestSerializer,
        responses={
            200: inline_serializer(
                name="CreatePasswordOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="CreatePasswordData",
                        fields={
                            "detail": serializers.CharField(),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
        },
        description="Create a password for the current user if one does not already exist.",
    )
    def post(self, request):
        user = request.user

        # Social users may have no password yet
        if user.has_usable_password():
            return error_response(
                message="Password already exists. Use change password instead.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="password_exists",
            )

        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if not new_password or not confirm_password:
            return error_response(
                    message="new_password and confirm_password are required.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    code="missing_password_fields",
                )

        if new_password != confirm_password:
            return error_response(
                message="Passwords do not match.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="validation_error",
                field_errors={"confirm_password": ["Passwords do not match."]},
                details={"confirm_password": ["Passwords do not match."]},
            )

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as e:
            return error_response(
                message="Invalid password.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="validation_error",
                field_errors={"new_password": list(e.messages)},
                details={"new_password": list(e.messages)},
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])

        return ok_response(
            {"detail": "Password created. You can now log in with email and password."},
            status_code=status.HTTP_200_OK,
        )








