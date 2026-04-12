#Standard/library
from datetime import datetime, timedelta
from decimal import Decimal
import logging
import stripe



#Django
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt


#DRF / spectacular
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import ListAPIView, RetrieveAPIView

from drf_spectacular.utils import (
    extend_schema,
    OpenApiParameter,
    OpenApiResponse,
    inline_serializer,
)


#Project
from propertylist_app.models import Payment, Room, WebhookReceipt, Notification
from propertylist_app.validators import (
    ensure_webhook_not_replayed,
    verify_webhook_signature,
)
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import standard_response_serializer
from propertylist_app.api.permissions import IsFinanceAdmin
from propertylist_app.api.pagination import StandardLimitOffsetPagination
from propertylist_app.api.serializers import (
    PaymentSerializer,
    PaymentTransactionListSerializer,
    StripeCheckoutRedirectResponseSerializer,
    StripeSuccessResponseSerializer,
    StripeCancelResponseSerializer,
    StripeCheckoutSessionCreateRequestSerializer,
    StripeWebhookEventRequestSerializer,
    StripeWebhookAckResponseSerializer,
    StripeWebhookErrorResponseSerializer,
    SavedCardsListResponseSerializer,
    SetupIntentResponseSerializer,
    DetailResponseSerializer,
)
from ..serializers import (
    PaymentTransactionDetailSerializer,
    ProviderWebhookRequestSerializer,
    ProviderWebhookResponseSerializer,
)



#Logger
logger_webhooks = logging.getLogger("rentout.webhooks")
logger = logger_webhooks




stripe.api_key = settings.STRIPE_SECRET_KEY


@extend_schema(
    request=StripeWebhookEventRequestSerializer,
    responses={
        200: inline_serializer(
            name="StripeWebhookAckOkResponse",
            fields={
                "ok": serializers.BooleanField(),
                "message": serializers.CharField(required=False, allow_null=True),
                "data": inline_serializer(
                    name="StripeWebhookAckData",
                    fields={
                        "detail": serializers.CharField(),
                        "event_id": serializers.CharField(required=False, allow_null=True),
                        "event_type": serializers.CharField(required=False, allow_null=True),
                        "payment_id": serializers.CharField(required=False, allow_null=True),
                    },
                ),
            },
        ),
        400: OpenApiResponse(response=ErrorResponseSerializer),
    },
    parameters=[
        OpenApiParameter(
            name="Stripe-Signature",
            type=str,
            location=OpenApiParameter.HEADER,
            required=True,
            description="Stripe webhook signature header used to verify the request.",
        ),
    ],
    auth=[],
    description=(
        "Stripe webhook endpoint. Verifies the Stripe-Signature header and processes "
        "Stripe event payloads. Currently handles checkout.session.completed and "
        "checkout.session.expired. Other event types are acknowledged and ignored."
    ),
)
@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        logger.warning("stripe_webhook_signature_failed")
        return Response(
            {
                "ok": False,
                "message": "Invalid payload or invalid Stripe signature.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
        
    except Exception:
        logger.exception("stripe_webhook_construct_event_failed")
        return Response(
            {
                "ok": False,
                "message": "Unable to construct Stripe event.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    logger.info(
        "stripe_webhook_received event_id=%s type=%s",
        event.get("id"),
        event.get("type"),
    )

    # Build a compact, storage-friendly payload for audit/debug.
    try:
        event_id = event.get("id") or ""
        evt_type = event.get("type")
        evt_created = event.get("created")
        evt_livemode = event.get("livemode")

        data_obj = ((event.get("data") or {}).get("object") or {})
        obj_id = data_obj.get("id")
        payment_intent = data_obj.get("payment_intent")
        metadata = data_obj.get("metadata") or {}

        payload_compact = {
            "id": event_id,
            "type": evt_type,
            "created": evt_created,
            "livemode": evt_livemode,
            "object": {
                "id": obj_id,
                "payment_intent": payment_intent,
                "metadata": metadata,
            },
        }

        payload_compact = json.loads(json.dumps(payload_compact))
    except Exception:
        event_id = event.get("id") or ""
        payload_compact = {"id": event_id, "type": event.get("type")}

    if event_id:
        try:
            with transaction.atomic():
                WebhookReceipt.objects.create(
                    source="stripe",
                    event_id=event_id,
                    payload=payload_compact,
                    headers={
                        "Stripe-Signature": request.META.get("HTTP_STRIPE_SIGNATURE", ""),
                        "User-Agent": request.META.get("HTTP_USER_AGENT", ""),
                        "Content-Type": request.META.get("CONTENT_TYPE", ""),
                    },
                )
        except IntegrityError:
            logger.info("stripe_webhook_duplicate event_id=%s", event_id)
            return ok_response(
                {
                    "detail": "duplicate",
                    "event_id": event_id,
                    "event_type": event.get("type"),
                },
                status_code=status.HTTP_200_OK,
            )
        except Exception:
            try:
                with transaction.atomic():
                    WebhookReceipt.objects.create(source="stripe", event_id=event_id)
            except Exception:
                pass

    evt_type = event.get("type")

    if evt_type == "checkout.session.completed":
        session = (event.get("data") or {}).get("object") or {}
        metadata = session.get("metadata") or {}

        payment_id = metadata.get("payment_id")
        payment_intent = session.get("payment_intent")

        if payment_id:
            try:
                with transaction.atomic():
                    updated = (
                        Payment.objects
                        .filter(id=payment_id)
                        .exclude(status="succeeded")
                        .update(
                            status="succeeded",
                            stripe_payment_intent_id=str(payment_intent or ""),
                        )
                    )

                    if updated == 1:
                        logger.info(
                            "stripe_webhook_payment_succeeded payment_id=%s payment_intent=%s",
                            payment_id,
                            (payment_intent or ""),
                        )

                        payment = Payment.objects.select_related("room").get(id=payment_id)
                        room = payment.room

                        if room:
                            today = timezone.now().date()
                            base = room.paid_until if (room.paid_until and room.paid_until > today) else today
                            room.paid_until = base + timedelta(days=30)
                            room.save(update_fields=["paid_until"])

                        Notification.objects.create(
                            user=payment.user,
                            type="confirmation",
                            title="Payment confirmed",
                            body="Your listing payment was successful.",
                            target_type="payment",
                            target_id=payment.id,
                        )
            except Exception:
                logger.exception("stripe_webhook_payment_success_failed")

        return ok_response(
            {
                "detail": "checkout.session.completed processed",
                "event_id": event_id,
                "event_type": evt_type,
                "payment_id": str(payment_id) if payment_id else None,
            },
            status_code=status.HTTP_200_OK,
        )

    elif evt_type == "checkout.session.expired":
        session = (event.get("data") or {}).get("object") or {}
        metadata = session.get("metadata") or {}
        payment_id = metadata.get("payment_id")

        if payment_id:
            updated = (
                Payment.objects
                .filter(id=payment_id, status="created")
                .update(status="canceled")
            )

            if updated == 1:
                logger.info(
                    "stripe_webhook_session_expired payment_id=%s",
                    payment_id,
                )

        return ok_response(
            {
                "detail": "checkout.session.completed processed",
                "event_id": event_id,
                "event_type": evt_type,
                "payment_id": str(payment_id) if payment_id else None,
            },
            status_code=status.HTTP_200_OK,
        )

    return ok_response(
        {
            "detail": f"ignored event {evt_type}",
            "event_id": event_id,
            "event_type": evt_type,
        },
        status_code=status.HTTP_200_OK,
    )
    
    
class ProviderWebhookView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="api_v1_webhooks_provider_incoming_create",
        request=ProviderWebhookRequestSerializer,
        responses={
            200: inline_serializer(
                name="ProviderWebhookOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "duplicate": serializers.BooleanField(required=False),
                    "note": serializers.CharField(required=False, allow_null=True),
                    "object_id": serializers.CharField(required=False, allow_null=True),
                },
            ),
            400: DetailResponseSerializer,
        },
        description="Receive and verify a provider webhook, store the receipt, and handle supported provider events.",
    )
    def post(self, request, provider):
        raw_body = request.body or b""
        provider_key = (provider or "default").strip().lower()

        secret = (
            settings.WEBHOOK_SECRETS.get(provider_key)
            or settings.WEBHOOK_SECRETS.get("default")
            or ""
        )
        if not secret:
            return Response(
                {"detail": f"No webhook secret configured for provider '{provider_key}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sig_header = request.headers.get("Stripe-Signature") or request.headers.get("X-Signature") or ""
        try:
            verify_webhook_signature(
                secret=secret,
                payload=raw_body,
                signature_header=sig_header,
                scheme="sha256=",
                clock_skew=300,
            )
        except Exception as e:
            return Response(
                {"detail": f"signature verification failed: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        event_id = (
            request.headers.get("X-Event-Id")
            or (payload.get("id") if isinstance(payload, dict) else None)
            or ""
        )
        if not event_id:
            import hashlib
            event_id = hashlib.sha256(raw_body).hexdigest()

        try:
            ensure_webhook_not_replayed(event_id, WebhookReceipt.objects)
        except Exception:
            return Response({"ok": True, "duplicate": True})

        try:
            hdrs = {
                "User-Agent": request.headers.get("User-Agent"),
                "Stripe-Signature": request.headers.get("Stripe-Signature"),
                "X-Signature": request.headers.get("X-Signature"),
                "X-Event-Id": request.headers.get("X-Event-Id"),
                "Content-Type": request.headers.get("Content-Type"),
            }
            WebhookReceipt.objects.create(
                source=provider_key,
                event_id=event_id,
                payload=payload,
                headers=hdrs,
            )
        except Exception:
            pass

        if provider_key == "stripe":
            return self._handle_stripe(payload)

        return Response({"ok": True})

    def _handle_stripe(self, payload: dict):
        try:
            evt_type = payload.get("type")
            data_obj = (payload.get("data") or {}).get("object") or {}
        except Exception:
            return Response({"ok": True, "note": "malformed stripe payload"})

        obj_id = data_obj.get("id")

        return Response(
            {"ok": True, "note": f"ignored stripe event {evt_type}", "object_id": obj_id}
        )




@extend_schema(
    operation_id="api_v1_webhooks_incoming_create",
    request=ProviderWebhookRequestSerializer,
    responses={200: ProviderWebhookResponseSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def webhook_in(request):
    sig_header = request.headers.get("X-Signature", "")
    verify_webhook_signature(
        secret="YOUR_WEBHOOK_SECRET",
        payload=request.body,
        signature_header=sig_header,
        scheme="sha256=",
        clock_skew=300,
    )
    event_id = request.headers.get("X-Event-Id") or request.data.get("id")
    ensure_webhook_not_replayed(event_id, WebhookReceipt.objects)
    WebhookReceipt.objects.create(source="provider", event_id=event_id)
    return Response({"ok": True})




class CreateListingCheckoutSessionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=StripeCheckoutSessionCreateRequestSerializer,
        responses={
            200: standard_response_serializer(
                "CreateListingCheckoutSessionResponse",
                StripeCheckoutRedirectResponseSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
            403: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description=(
            "Creates a Stripe Checkout Session for the specified room listing fee. "
            "Request body may include an optional payment_method_id. "
            "Returns the Stripe-hosted checkout_url and session_id inside the standard envelope."
        ),
    )
    def post(self, request, pk):
        room = get_object_or_404(Room.objects.filter(is_deleted=False), pk=pk)

        # Only the property owner can pay to list this room
        if room.property_owner != request.user:
            return Response(
                {
                    "ok": False,
                    "message": "You are not allowed to pay for this listing.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        user = request.user

        # Make sure user has a profile
        profile = getattr(user, "profile", None)
        if profile is None:
            profile = user.profile = UserProfile.objects.create(user=user)

        # Ensure a Stripe Customer exists for this user
        if not profile.stripe_customer_id:
            stripe_customer = stripe.Customer.create(
                email=user.email or None,
                name=user.get_full_name() or user.username,
            )

            stripe_customer_id = getattr(stripe_customer, "id", None)
            if stripe_customer_id:
                profile.stripe_customer_id = str(stripe_customer_id)
                profile.save(update_fields=["stripe_customer_id"])

        customer_id = profile.stripe_customer_id or None

        # Listing fee – still £1.00 for 4 weeks
        amount_gbp = Decimal("1.00")
        amount_pence = int(amount_gbp * 100)

        # Create our internal Payment record
        payment = Payment.objects.create(
            user=user,
            room=room,
            amount=amount_gbp,
            currency="GBP",
            status="created",
        )

        # Optional: read a selected saved card id from the body (for future use)
        _payment_method_id = request.data.get("payment_method_id")  # may be None

        base = (settings.SITE_URL or "").rstrip("/")

        success_path = reverse("v1:payments-success")
        cancel_path = reverse("v1:payments-cancel")

        # Create the Stripe Checkout Session
        session = stripe.checkout.Session.create(
            mode="payment",
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "gbp",
                        "product_data": {
                            "name": f"Listing fee for: {room.title}",
                        },
                        "unit_amount": amount_pence,
                    },
                    "quantity": 1,
                }
            ],
            success_url=(
                f"{base}{success_path}"
                f"?session_id={{CHECKOUT_SESSION_ID}}&payment_id={payment.id}"
            ),
            cancel_url=(
                f"{base}{cancel_path}"
                f"?payment_id={payment.id}"
            ),
            metadata={
                "payment_id": str(payment.id),
                "room_id": str(room.id),
                "user_id": str(user.id),
            },
        )

        # Safely extract session id + checkout URL (works for real Stripe + dict fakes)
        session_id = getattr(session, "id", None)
        checkout_url = getattr(session, "url", None)

        if isinstance(session, dict):
            session_id = session.get("id")
            checkout_url = session.get("url")

        payment.stripe_checkout_session_id = str(session_id) if session_id else ""
        payment.save(update_fields=["stripe_checkout_session_id"])

        return ok_response(
            {
                "checkout_url": checkout_url,
                "session_id": str(session_id) if session_id else None,
            },
            message="Checkout session created successfully.",
            status_code=status.HTTP_200_OK,
        )




class SavedCardsListView(APIView):
    """
    Returns up to 4 saved card payment methods for the current user
    using their Stripe Customer ID.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: SavedCardsListResponseSerializer,
            502: DetailResponseSerializer,
        },
        description="Return up to 4 saved card payment methods for the current user.",
    )
    def get(self, request):
        user = request.user
        profile = getattr(user, "profile", None)

        # If no Stripe customer exists, return empty list
        if profile is None or not profile.stripe_customer_id:
            return Response({"cards": []})

        try:
            # Stripe returns a ListObject -> convert to standard dict
            pm_list = stripe.PaymentMethod.list(
                customer=profile.stripe_customer_id,
                type="card",
                limit=4,
            )

            pm_list = pm_list.to_dict()  # <--- THIS FIXES THE TYPE ISSUE

        except Exception:
            return Response(
                {"detail": "Unable to fetch saved cards from Stripe."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        cards = []

        # pm_list["data"] is now a Python list of dicts
        for pm in pm_list.get("data", []):
            card_info = pm.get("card", {})

            cards.append(
                {
                    "id": pm.get("id"),
                    "brand": card_info.get("brand"),
                    "last4": card_info.get("last4"),
                    "exp_month": card_info.get("exp_month"),
                    "exp_year": card_info.get("exp_year"),
                }
            )

        return Response({"cards": cards})  
      
      
      
class DetachSavedCardView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="DetachSavedCardOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="DetachSavedCardData",
                        fields={
                            "detail": serializers.CharField(),
                        },
                    ),
                },
            ),
            400: DetailResponseSerializer,
            401: OpenApiResponse(description="Authentication required."),
            502: DetailResponseSerializer,
        },
        description="Detach a saved Stripe card for the current user.",
    )
    def post(self, request, pm_id):
        profile = getattr(request.user, "profile", None)
        if not profile or not profile.stripe_customer_id:
            return Response(
                {"detail": "No Stripe customer found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            stripe.PaymentMethod.detach(pm_id)
        except Exception:
            return Response(
                {"detail": "Unable to detach saved card."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return ok_response(
            {"detail": "Card removed."},
            status_code=status.HTTP_200_OK,
        )


class PaymentTransactionsListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentTransactionListSerializer


    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payment.objects.none()
        qs = Payment.objects.filter(user=self.request.user).select_related("room").order_by("-created_at")

        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(room__title__icontains=q) |
                Q(stripe_payment_intent_id__icontains=q) |
                Q(stripe_checkout_session_id__icontains=q)
            )

        range_key = self.request.query_params.get("range")
        now = timezone.now()

        if range_key == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
            qs = qs.filter(created_at__gte=start, created_at__lte=end)

        elif range_key == "yesterday":
            start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            qs = qs.filter(created_at__gte=start, created_at__lt=end)

        elif range_key == "last_7_days":
            qs = qs.filter(created_at__gte=now - timedelta(days=7), created_at__lte=now)

        elif range_key == "this_month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            qs = qs.filter(created_at__gte=start, created_at__lte=now)

        elif range_key == "custom":
            start = self.request.query_params.get("start")
            end = self.request.query_params.get("end")
            if start and end:
                qs = qs.filter(created_at__date__gte=start, created_at__date__lte=end)

        return qs

    
    @extend_schema(
        responses={
            200: inline_serializer(
                name="PaginatedPaymentTransactionListResponse",
                fields={
                    "count": serializers.IntegerField(),
                    "next": serializers.URLField(required=False, allow_null=True),
                    "previous": serializers.URLField(required=False, allow_null=True),
                    "results": PaymentTransactionListSerializer(many=True),
                },
            )
        },
        parameters=[
            OpenApiParameter(
                name="q",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search by room title, Stripe payment intent id, or Stripe checkout session id.",
            ),
            OpenApiParameter(
                name="range",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Date range filter. Supported values: today, yesterday, last_7_days, this_month, custom.",
            ),
            OpenApiParameter(
                name="offset",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of transactions to skip before starting the result set.",
            ),
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of transactions to return.",
            ),
            OpenApiParameter(
                name="start",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Custom range start date. Used when range=custom.",
            ),
            OpenApiParameter(
                name="end",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Custom range end date. Used when range=custom.",
            ),
        ],
        description="List payment transactions in DRF paginated format (count/next/previous/results). Supports search and date-range filtering.",
        )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
        
        
        
        
class PaymentTransactionDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentTransactionDetailSerializer

    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user).select_related("room")




class CreateSetupIntentView(APIView):
    """
    Creates a Stripe SetupIntent for the logged-in user so they can add/save a card
    using Stripe Elements (do NOT send raw card details to backend).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="CreateSetupIntentOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": SetupIntentResponseSerializer(),
                },
            ),
            401: OpenApiResponse(description="Authentication required."),
            502: DetailResponseSerializer,
        },
        description="Create a Stripe SetupIntent for the current user and return it in the standard envelope.",
    )
    def post(self, request):
        user = request.user

        # Ensure profile exists (same pattern you used in checkout)
        profile = getattr(user, "profile", None)
        if profile is None:
            profile = user.profile = UserProfile.objects.create(user=user)

        # Ensure Stripe Customer exists
        if not profile.stripe_customer_id:
            stripe_customer = stripe.Customer.create(
                email=user.email or None,
                name=user.get_full_name() or user.username,
            )

            stripe_customer_id = getattr(stripe_customer, "id", None)
            if not stripe_customer_id:
                return Response(
                    {"detail": "Unable to create Stripe customer."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            profile.stripe_customer_id = str(stripe_customer_id)
            profile.save(update_fields=["stripe_customer_id"])

        # Create SetupIntent (used by Stripe Elements to save a card)
        try:
            setup_intent = stripe.SetupIntent.create(
                customer=profile.stripe_customer_id,
                payment_method_types=["card"],
                usage="off_session",
            )
        except Exception:
            return Response(
                {"detail": "Unable to create setup intent."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        client_secret = getattr(setup_intent, "client_secret", None)
        if not client_secret:
            # if stripe returned a dict instead of an object in some mocks
            client_secret = setup_intent.get("client_secret") if isinstance(setup_intent, dict) else None

        if not client_secret:
            return Response(
                {"detail": "Setup intent missing client secret."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return ok_response(
            {
                "clientSecret": client_secret,
                "publishableKey": getattr(settings, "STRIPE_PUBLISHABLE_KEY", ""),
            },
            status_code=status.HTTP_200_OK,
        )
       
               
class SetDefaultSavedCardView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="SetDefaultSavedCardOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="SetDefaultSavedCardData",
                        fields={
                            "detail": serializers.CharField(),
                        },
                    ),
                },
            ),
            400: DetailResponseSerializer,
            401: OpenApiResponse(description="Authentication required."),
            502: DetailResponseSerializer,
        },
        description="Set the default saved Stripe card for the current user.",
    )
    def post(self, request, pm_id):
        profile = getattr(request.user, "profile", None)
        if not profile or not profile.stripe_customer_id:
            return Response(
                {"detail": "No Stripe customer found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            stripe.Customer.modify(
                profile.stripe_customer_id,
                invoice_settings={"default_payment_method": pm_id},
            )
        except Exception:
            return Response(
                {"detail": "Unable to set default card."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return ok_response(
            {"detail": "Default card updated."},
            status_code=status.HTTP_200_OK,
        )





class StripeSuccessView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        responses={
            200: standard_response_serializer(
                "StripeSuccessResponse",
                StripeSuccessResponseSerializer,
            ),
        },
        parameters=[
            OpenApiParameter(
                name="session_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Stripe Checkout Session ID returned by Stripe redirect.",
            ),
            OpenApiParameter(
                name="payment_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Internal Payment ID included in redirect URL.",
            ),
        ],
        auth=[],
        description=(
            "Landing endpoint after successful Stripe Checkout redirect. "
            "This endpoint acknowledges the redirect only; the Stripe webhook "
            "is responsible for final payment confirmation and room listing activation."
        ),
    )
    def get(self, request):
        session_id = request.query_params.get("session_id")
        payment_id = request.query_params.get("payment_id")

        return ok_response(
            {
                "detail": "Payment success received. (Webhook will finalise the room.)",
                "session_id": session_id,
                "payment_id": payment_id,
            },
            message="Stripe success redirect received.",
            status_code=status.HTTP_200_OK,
        )



class StripeCancelView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        responses={
            200: standard_response_serializer(
                "StripeCancelResponse",
                StripeCancelResponseSerializer,
            ),
        },
        parameters=[
            OpenApiParameter(
                name="payment_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Internal Payment ID included in redirect URL.",
            ),
        ],
        auth=[],
        description="Landing endpoint after a cancelled Stripe Checkout redirect.",
    )
    def get(self, request):
        payment_id = request.query_params.get("payment_id")

        return ok_response(
            {
                "detail": "Payment cancelled.",
                "payment_id": payment_id,
            },
            message="Stripe cancel redirect received.",
            status_code=status.HTTP_200_OK,
        )
               
