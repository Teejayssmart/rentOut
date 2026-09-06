import json



from django.db.models import Count, Exists, Max, OuterRef, Q, Subquery, Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.conf import settings

from rest_framework import generics, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import filters
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiResponse,
    inline_serializer,
    OpenApiParameter,
)
from drf_spectacular.types import OpenApiTypes


from propertylist_app.services.message_threads import (
    get_or_create_canonical_thread,
)

from urllib.parse import quote
from urllib.request import Request, urlopen

from django.db.models import Count, Exists, Max, OuterRef, Q, Subquery, Prefetch, IntegerField
from django.db.models.functions import Coalesce




from propertylist_app.models import (
    Message,
    MessageRead,
    MessageThread,
    MessageThreadState,
    Notification,
    Room,
    SavedRoom,
    UserProfile,
)
from propertylist_app.api.pagination import StandardLimitOffsetPagination
from propertylist_app.api.throttling import MessageUserThrottle, MessagingScopedThrottle
from propertylist_app.services.realtime import push_user_realtime_event
from propertylist_app.api.schema_serializers import ErrorResponseSerializer
from propertylist_app.api.schema_helpers import (
    standard_response_serializer,
    standard_paginated_response_serializer,
)
from propertylist_app.api.serializers import (
    InboxItemSerializer,
    MessageSerializer,
    MessageThreadSerializer,
    MessageThreadStateUpdateSerializer,
    NotificationSerializer,
    NotificationMarkReadResponseSerializer,
    NotificationMarkAllReadResponseSerializer,
    ThreadRestoreResponseSerializer,
    ThreadStateResponseSerializer,
    MessageCreateSerializer,
    DetailResponseSerializer,
    RoomSerializer,

)
from ..serializers import (
    ContactMessageSerializer,
    ThreadMoveToBinRequestSerializer,
    ThreadSetLabelRequestSerializer,
    ThreadMarkReadRequestSerializer,
)
from .common import ok_response, _pagination_meta, _wrap_response_success





class EmptyDataSerializer(serializers.Serializer):
    pass

def _role_scoped_threads(user):
    profile, _ = UserProfile.objects.get_or_create(
        user=user
    )
    active_role = profile.role

    qs = MessageThread.objects.filter(
        participants=user
    )

    if active_role == "landlord":
        return qs.filter(
            Q(landlord=user)
            | Q(
                landlord__isnull=True,
                seeker__isnull=True,
            )
        )

    return qs.filter(
        Q(seeker=user)
        | Q(
            landlord__isnull=True,
            seeker__isnull=True,
        )
    )






class InboxListView(APIView):
    """
    GET /api/inbox/

    Returns a merged list:
      - message threads (latest message per thread)
      - notifications

    Frontend can render them in one inbox screen.
    """
    permission_classes = [IsAuthenticated]
    pagination_class = StandardLimitOffsetPagination




    @extend_schema(
        responses={
            200: inline_serializer(
                name="InboxListOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(allow_null=True, required=False),
                    "data": InboxItemSerializer(many=True),
                },
            )
        },
        description="List inbox items (merged notifications and message threads) wrapped in ok_response. Not paginated.",
    )
    def get(self, request):
        user = request.user

        # 1) notifications
        profile, _ = UserProfile.objects.get_or_create(
            user=user
        )
        active_role = profile.role

        notif_qs = (
            Notification.objects
            .filter(
                user=user,
                audience__in=[
                    active_role,
                    Notification.Audience.BOTH,
                ],
            )
            .order_by("-created_at")[:200]
        )

        notif_items = []
        for notification in notif_qs:
            notification_data = NotificationSerializer(notification).data

            notif_items.append(
                {
                    "kind": "notification",
                    "created_at": notification.created_at,
                    "title": notification.title or "Notification",
                    "preview": (notification.body or "")[:140],
                    "is_read": notification.is_read,
                    "notification_id": notification.id,
                    "deep_link": notification_data["deep_link"],
                }
            )

        # 2) message threads (use latest message timestamp as created_at)
        #    assumes related name: thread.messages (your code shows thread.messages usage)


        # 2) message threads (use latest message timestamp as created_at)
        threads = (
            _role_scoped_threads(user)
            .annotate(
                last_msg_at=Max("messages__created"),
                unread_count=Count(
                    "messages",
                    filter=(
                        (
                            Q(messages__metadata__system_event=True)
                            | ~Q(messages__sender=user)
                        )
                        & ~Q(messages__reads__user=user)
                    ),
                    distinct=True,
                ),
            )
            .prefetch_related(
                "participants__profile",
                Prefetch(
                    "messages",
                    queryset=(
                        Message.objects
                        .order_by("-created")[:1]
                    ),
                    to_attr="_prefetched_last_messages",
                ),
            )
            .order_by("-last_msg_at")
        )[:200]

        thread_items = []
        for t in threads:
            prefetched_messages = getattr(
                t,
                "_prefetched_last_messages",
                [],
            )
            last_msg = (
                prefetched_messages[0]
                if prefetched_messages
                else None
            )
            if not last_msg:
                continue

            unread = getattr(t, "unread_count", 0)

            prefetched_participants = getattr(
                t,
                "_prefetched_objects_cache",
                {},
            ).get("participants", [])

            other_party = next(
                (
                    participant
                    for participant in prefetched_participants
                    if participant.id != user.id
                ),
                None,
            )
            title = getattr(other_party, "username", None) or "Message"

            thread_items.append(
                {
                    "kind": "thread",
                    "created_at": getattr(last_msg, "created", None) or getattr(t, "last_msg_at", None),  # FIX
                    "title": title,
                    "preview": (getattr(last_msg, "body", "") or "")[:140],
                    "is_read": unread == 0,
                    "thread_id": t.id,
                    "deep_link": f"/app/threads/{t.id}",
                    "cta_url": f"/messages?thread={t.id}",
                }
            )

        # merge + sort
        merged = notif_items + thread_items
        merged.sort(key=lambda x: (x["created_at"] is None, x["created_at"]), reverse=True)

        items = merged[:250]

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(items, request, view=self)
        ser = InboxItemSerializer(page, many=True)

        return _wrap_response_success(
            paginator.get_paginated_response(ser.data)
        )







def _fetch_ideal_postcodes_suggestions(postcode: str):
    """
    Server-side postcode lookup via Ideal Postcodes API.
    Returns a simplified list:
    [
        {"id": "...", "label": "..."},
        ...
    ]
    """
    api_key = getattr(settings, "IDEAL_POSTCODES_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("IDEAL_POSTCODES_API_KEY is not configured.")

    encoded_postcode = quote(postcode)
    url = f"https://api.ideal-postcodes.co.uk/v1/postcodes/{encoded_postcode}?api_key={quote(api_key)}"

    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "RentOut/1.0 address-lookup",
        },
        method="GET",
    )

    with urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8")
        payload = json.loads(body)

    results = payload.get("result", [])
    addresses = []

    for idx, item in enumerate(results):
        if isinstance(item, str):
            addresses.append(
                {
                    "id": f"{postcode}-{idx}",
                    "label": item,
                }
            )
        elif isinstance(item, dict):
            label = item.get("label") or item.get("line_1") or item.get("postcode")
            if label:
                addresses.append(
                    {
                        "id": str(item.get("id") or item.get("udprn") or f"{postcode}-{idx}"),
                        "label": label,
                    }
                )

    return addresses





# --------------------
# Save / Unsave rooms
# --------------------
class RoomSaveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            201: inline_serializer(
                name="RoomSaveOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="RoomSaveData",
                        fields={
                            "saved": serializers.BooleanField(),
                        },
                    ),
                },
            ),
            404: DetailResponseSerializer,
        },
        description="Save a room for the authenticated user. Returns ok_response envelope.",
    )
    def post(self, request, pk, *args, **kwargs):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        SavedRoom.objects.get_or_create(user=request.user, room=room)
        return ok_response({"saved": True}, status_code=status.HTTP_201_CREATED)

    @extend_schema(
    responses={
        200: standard_response_serializer(
            "RoomSaveDeleteResponse",
            EmptyDataSerializer,
        ),
        401: OpenApiResponse(response=ErrorResponseSerializer),
        404: OpenApiResponse(response=ErrorResponseSerializer),
    },
        description="Remove a saved room for the authenticated user.",
    )
    def delete(self, request, pk, *args, **kwargs):
        room = get_object_or_404(Room.objects.alive(), pk=pk)
        SavedRoom.objects.filter(user=request.user, room=room).delete()
        return ok_response(
            {},
            message="Saved room removed successfully.",
            status_code=status.HTTP_200_OK,
        )


# views.py

# FILE TO OPEN:
# propertylist_app/api/views.py
#
# REPLACE your existing RoomSaveToggleView class with this complete version.
# This wraps every 200 success response in A3 envelope using ok_response(...)
# and leaves the logic unchanged.




class RoomSaveToggleView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT},
    )
    def post(self, request, pk, *args, **kwargs):
        room = get_object_or_404(Room.objects.alive(), pk=pk)

        saved_qs = SavedRoom.objects.filter(user=request.user, room=room)

        if saved_qs.exists():
            saved_qs.delete()
            return ok_response(
                {"saved": False, "saved_at": None},
                status_code=status.HTTP_200_OK,
            )

        saved = SavedRoom.objects.create(user=request.user, room=room)
        return ok_response(
            {"saved": True, "saved_at": saved.saved_at if hasattr(saved, "saved_at") else timezone.now()},
            status_code=status.HTTP_200_OK,
        )

    @extend_schema(
    responses={
        200: standard_response_serializer(
            "RoomSaveToggleDeleteResponse",
            EmptyDataSerializer,
        ),
        401: OpenApiResponse(response=ErrorResponseSerializer),
        404: OpenApiResponse(response=ErrorResponseSerializer),
    },
    )
    def delete(self, request, pk):
        room = get_object_or_404(Room, pk=pk)

        SavedRoom.objects.filter(user=request.user, room=room).delete()

        return ok_response(
            {},
            message="Saved room removed successfully.",
            status_code=status.HTTP_200_OK,
        )





class MySavedRoomsView(generics.ListAPIView):
    serializer_class = RoomSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardLimitOffsetPagination

    def get_queryset(self):
        # drf-spectacular calls get_queryset without a real request/user context sometimes.
        # Avoid raising during schema generation.
        if getattr(self, "swagger_fake_view", False):
            return Room.objects.none()

        user = self.request.user
        if not user or not user.is_authenticated:
            return Room.objects.none()

        saved_qs = SavedRoom.objects.filter(user=user)

        latest_saved_id = (
            SavedRoom.objects.filter(user=user, room=OuterRef("pk"))
            .order_by("-id")
            .values("id")[:1]
        )

        qs = (
            Room.objects.alive()
            .filter(id__in=saved_qs.values_list("room_id", flat=True))
            .annotate(saved_id=Subquery(latest_saved_id))
            .select_related("category")
        )

        ordering = (self.request.query_params.get("ordering") or "-saved_at").strip()
        mapping = {
            "saved_at": "saved_id",
            "-saved_at": "-saved_id",
            "price_per_month": "price_per_month",
            "-price_per_month": "-price_per_month",
            "avg_rating": "avg_rating",
            "-avg_rating": "-avg_rating",
        }
        return qs.order_by(mapping.get(ordering, "-saved_id"))

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx





#---------------------
# Messaging
# --------------------

@extend_schema_view(
    get=extend_schema(
        parameters=[
            OpenApiParameter(
                name="role",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["landlord", "seeker"],
                description=(
                    "Return threads where the authenticated user has "
                    "the authoritative landlord or seeker role."
                ),
            ),
        ],
    ),
)
class MessageThreadListCreateView(generics.ListCreateAPIView):

    """
    GET /api/v1/messages/threads/

    Query params:
      - folder : inbox (default) | sent | bin | new | waiting_reply
      - role   : landlord | seeker
      - label  : filter by per-user label
      - q      : search in message body or participant username
      - sort_by: latest (default) | oldest
    """
    
    serializer_class = MessageThreadSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardLimitOffsetPagination
    throttle_classes = [UserRateThrottle, MessagingScopedThrottle]  # keep off if tests expect no 429

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MessageThread.objects.none()

        user = self.request.user
        params = self.request.query_params
        
        
        hidden_by_delete = MessageThreadState.objects.filter(
            user=user,
            thread_id=OuterRef("thread_id"),
            deleted_at__isnull=False,
            deleted_at__gte=OuterRef("created"),
        )
        
        

        unread_messages = (
            Message.objects
            .filter(thread=OuterRef("pk"))
            .annotate(
                hidden_by_delete=Exists(hidden_by_delete)
            )
            .filter(hidden_by_delete=False)
            .filter(
                Q(metadata__system_event=True)
                | ~Q(sender=user)
            )
            .exclude(reads__user=user)
            .values("thread")
            .annotate(total=Count("id", distinct=True))
            .values("total")[:1]
        )

        qs = (
            MessageThread.objects
            .filter(participants=user)
            .annotate(
                unread_count=Coalesce(
                    Subquery(
                        unread_messages,
                        output_field=IntegerField(),
                    ),
                    0,
                ),
            )
            .prefetch_related(
                "participants__profile",
                Prefetch(
                    "messages",
                    queryset=(
                        Message.objects
                        .select_related("sender")
                        .prefetch_related("reads")
                        .order_by("-created")[:1]
                    ),
                    to_attr="_prefetched_last_messages",
                ),
            )
        )


        requested_role = (params.get("role") or "").strip().lower()

        if requested_role not in {"", "landlord", "seeker"}:
            raise ValidationError(
                {
                    "role": (
                        "Invalid role. Expected 'landlord' or 'seeker'."
                    )
                }
            )

        profile, _ = UserProfile.objects.get_or_create(
            user=user
        )
        active_role = profile.role

        if active_role == "landlord":
            qs = qs.filter(
                Q(landlord=user)
                | Q(
                    landlord__isnull=True,
                    seeker__isnull=True,
                )
            )
        else:
            qs = qs.filter(
                Q(seeker=user)
                | Q(
                    landlord__isnull=True,
                    seeker__isnull=True,
                )
            )

        deleted_states = (
            MessageThreadState.objects
            .filter(
                user=user,
                deleted_at__isnull=False,
            )
            .values(
                "thread_id",
                "deleted_at",
            )
        )

        for deleted_state in deleted_states:
            has_new_incoming_message = (
                Message.objects
                .filter(
                    thread_id=deleted_state["thread_id"],
                    created__gt=deleted_state["deleted_at"],
                    message_type=Message.TYPE_TEXT,
                )
                .exclude(sender=user)
                .filter(
                    Q(metadata__system_event__isnull=True)
                    | Q(metadata__system_event=False)
                )
                .exists()
            )

            if not has_new_incoming_message:
                qs = qs.exclude(id=deleted_state["thread_id"])

        folder = (params.get("folder") or "").strip().lower()

        bin_thread_ids = list(
            MessageThreadState.objects
            .filter(user=user, in_bin=True)
            .values_list("thread_id", flat=True)
        )

        if folder == "bin":
            qs = qs.filter(id__in=bin_thread_ids or [-1])
        else:
            if bin_thread_ids:
                qs = qs.exclude(id__in=bin_thread_ids)

            if folder == "new":
                unread_exists = (
                    Message.objects
                    .filter(thread=OuterRef("pk"))
                    .annotate(
                        hidden_by_delete=Exists(hidden_by_delete)
                    )
                    .filter(hidden_by_delete=False)
                    .filter(
                        Q(metadata__system_event=True)
                        | ~Q(sender=user)
                    )
                    .exclude(reads__user=user)
                )

                qs = qs.annotate(
                    has_unread=Exists(unread_exists)
                ).filter(
                    has_unread=True
                )

            elif folder == "sent":
                last_sender_subq = (
                    Message.objects
                    .filter(thread=OuterRef("pk"))
                    .order_by("-created")
                    .values("sender_id")[:1]
                )

                qs = qs.annotate(
                    last_sender_id=Subquery(last_sender_subq)
                ).filter(
                    last_sender_id=user.id
                )

        label = (params.get("label") or "").strip()

        if label:
            label_ids = (
                MessageThreadState.objects
                .filter(
                    user=user,
                    label=label,
                    in_bin=False,
                )
                .values_list("thread_id", flat=True)
            )

            qs = qs.filter(id__in=label_ids)

        search = (params.get("q") or "").strip()

        if search:
            qs = qs.filter(
                Q(messages__body__icontains=search)
                | Q(participants__username__icontains=search)
            ).distinct()

        sort_by = (params.get("sort_by") or "").strip().lower()

        if sort_by == "oldest":
            qs = qs.order_by("created_at")

        elif sort_by in {"name", "alphabetical"}:
            UserModel = get_user_model()

            other_username_subq = (
                UserModel.objects
                .filter(message_threads__id=OuterRef("pk"))
                .exclude(id=user.id)
                .order_by("username")
                .values("username")[:1]
            )

            qs = qs.annotate(
                other_username=Subquery(other_username_subq)
            ).order_by(
                "other_username",
                "-created_at",
            )

        else:
            qs = qs.order_by("-created_at")

        return qs.distinct()

    def _attach_state_for_user(self, user, threads):
        """
        Attach obj._state_for_user = MessageThreadState(...) for each thread
        so the serializer can use it without extra queries.
        """
        ids = [t.id for t in threads]
        if not ids:
            return

        states = MessageThreadState.objects.filter(
            user=user,
            thread_id__in=ids,
        )
        state_map = {st.thread_id: st for st in states}
        for t in threads:
            setattr(t, "_state_for_user", state_map.get(t.id))

    @extend_schema(
        responses={
            200: inline_serializer(
                name="PaginatedMessageThreadListOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": MessageThreadSerializer(many=True),
                    "meta": inline_serializer(
                        name="MessageThreadListMeta",
                        fields={
                            "count": serializers.IntegerField(),
                            "next": serializers.CharField(required=False, allow_null=True),
                            "previous": serializers.CharField(required=False, allow_null=True),
                        },
                    ),
                    "count": serializers.IntegerField(required=False, allow_null=True),
                    "next": serializers.CharField(required=False, allow_null=True),
                    "previous": serializers.CharField(required=False, allow_null=True),
                    "results": MessageThreadSerializer(many=True, required=False),
                },
            )
        },
        parameters=[
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of threads to return.",
            ),
            OpenApiParameter(
                name="role",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["landlord", "seeker"],
                description=(
                    "Return only threads where the authenticated user has "
                    "the authoritative landlord or seeker role."
                ),
            ),
            
            OpenApiParameter(
                name="offset",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of threads to skip before starting the result set.",
            ),
            OpenApiParameter(
                name="folder",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Folder filter: inbox, sent, bin, new, or waiting_reply.",
            ),
            OpenApiParameter(
                name="label",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Per-user label filter.",
            ),
            OpenApiParameter(
                name="q",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search in message body or participant username.",
            ),
            OpenApiParameter(
                name="sort_by",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Sort threads by latest, oldest, name, or alphabetical.",
            ),
        ],
        description="List message threads wrapped in ok_response. Supports folder, label, search, sort, and limit/offset pagination.",
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            self._attach_state_for_user(request.user, page)
            serializer = self.get_serializer(page, many=True)
            meta = _pagination_meta(self.paginator)
            return ok_response(serializer.data, meta=meta, status_code=200)

        self._attach_state_for_user(request.user, queryset)
        serializer = self.get_serializer(queryset, many=True)
        return ok_response(serializer.data, status_code=200)

    @extend_schema(
        request=MessageThreadSerializer,
        responses={
            201: standard_response_serializer(
                "MessageThreadCreateResponse",
                MessageThreadSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Create a new message thread between exactly two participants: you and one other user.",
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return ok_response(
            serializer.data,
            message="Message thread created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def perform_create(self, serializer):
        participants = set(serializer.validated_data.get("participants", []))
        participants.add(self.request.user)
        if len(participants) != 2:
            raise ValidationError(
                {"participants": "Threads must have exactly 2 participants (you + one other user)."}
            )

        p_list = list(participants)
        existing = (
            MessageThread.objects.filter(participants=p_list[0])
            .filter(participants=p_list[1])
            .annotate(num_participants=Count("participants"))
            .filter(num_participants=2)
        )
        if existing.exists():
            raise ValidationError({"detail": "A thread between you two already exists."})

        thread = serializer.save()
        thread.participants.set(participants)



class MessageThreadDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/messages/threads/<thread_id>/

    Return one message thread when the authenticated user is a participant.
    """

    serializer_class = MessageThreadSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle, MessagingScopedThrottle]

    lookup_url_kwarg = "thread_id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MessageThread.objects.none()

        user = self.request.user
        
        profile, _ = UserProfile.objects.get_or_create(
            user=user
        )
        active_role = profile.role
        
        hidden_by_delete = MessageThreadState.objects.filter(
            user=user,
            thread_id=OuterRef("thread_id"),
            deleted_at__isnull=False,
            deleted_at__gte=OuterRef("created"),
        )

        unread_messages = (
            Message.objects
            .filter(thread=OuterRef("pk"))
            .annotate(
                hidden_by_delete=Exists(hidden_by_delete)
            )
            .filter(hidden_by_delete=False)
            .filter(
                Q(metadata__system_event=True)
                | ~Q(sender=user)
            )
            .exclude(reads__user=user)
            .values("thread")
            .annotate(total=Count("id", distinct=True))
            .values("total")[:1]
        )

        qs = (
            MessageThread.objects
            .filter(participants=user)
        )

        if active_role == "landlord":
            qs = qs.filter(
                Q(landlord=user)
                | Q(
                    landlord__isnull=True,
                    seeker__isnull=True,
                )
            )
        else:
            qs = qs.filter(
                Q(seeker=user)
                | Q(
                    landlord__isnull=True,
                    seeker__isnull=True,
                )
            )

        return (
            qs
            .annotate(
                unread_count=Coalesce(
                    Subquery(
                        unread_messages,
                        output_field=IntegerField(),
                    ),
                    0,
                ),
            )
            .prefetch_related(
                "participants__profile",
                "messages",
            )
            .distinct()
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()

        states = MessageThreadState.objects.filter(
            user=request.user,
            thread=instance,
        ).first()

        setattr(instance, "_state_for_user", states)

        serializer = self.get_serializer(instance)

        return ok_response(
            serializer.data,
            status_code=status.HTTP_200_OK,
        )




class MessageThreadStateView(APIView):
    """
    PATCH /api/messages/threads/<thread_id>/state/

    Updates the *current user's* view of a thread:
    - label: viewing_scheduled / viewing_done / good_fit / unsure / not_a_fit / paperwork_pending / no_status
    - in_bin: true / false
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=MessageThreadStateUpdateSerializer,
        responses={
            200: standard_response_serializer(
                "MessageThreadStateUpdateResponse",
                ThreadStateResponseSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        }
    )
    def patch(self, request, thread_id):
        profile, _ = UserProfile.objects.get_or_create(
            user=request.user
        )
        active_role = profile.role

        qs = MessageThread.objects.filter(
            participants=request.user
        )

        if active_role == "landlord":
            qs = qs.filter(
                Q(landlord=request.user)
                | Q(
                    landlord__isnull=True,
                    seeker__isnull=True,
                )
            )
        else:
            qs = qs.filter(
                Q(seeker=request.user)
                | Q(
                    landlord__isnull=True,
                    seeker__isnull=True,
                )
            )

        thread = get_object_or_404(
            qs,
            pk=thread_id,
        )

        ser = MessageThreadStateUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        state, _ = MessageThreadState.objects.get_or_create(
            user=request.user,
            thread=thread,
        )

        if "label" in data:
            state.label = data["label"]

        if "in_bin" in data:
            state.in_bin = bool(data["in_bin"])

        state.save()

        payload = {
            "thread": thread.id,
            "label": state.label or None,
            "in_bin": state.in_bin,
        }

        return ok_response(
            payload,
            message="Thread state updated successfully.",
            status_code=status.HTTP_200_OK,
        )




class MessageStatsView(APIView):
    """
    GET /api/messages/stats/

    Used by the home screen to power quick filters like
    â€œMessages > Good Fitâ€.

    Returns counts scoped to the current user:
      - total_threads: all threads Iâ€™m in (excluding my Bin)
      - total_unread: unread messages in those threads
      - good_fit.threads: threads labelled 'good_fit' for me
      - good_fit.unread: unread messages inside those threads
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="MessageStatsResponse",
                fields={
                    "total_threads": serializers.IntegerField(),
                    "total_unread": serializers.IntegerField(),
                    "good_fit": inline_serializer(
                        name="MessageStatsGoodFit",
                        fields={
                            "threads": serializers.IntegerField(),
                            "unread": serializers.IntegerField(),
                        },
                    ),
                },
            )
        },
            description="Return message statistics for the authenticated user, including total threads, total unread messages, and good-fit thread counts.",
    )
    def get(self, request):
        user = request.user

        # Base threads: visible in my active role
        base_threads = _role_scoped_threads(user)

        # Exclude threads that *I* put in Bin
        bin_thread_ids = list(
            MessageThreadState.objects
            .filter(user=user, in_bin=True)
            .values_list("thread_id", flat=True)
        )
        if bin_thread_ids:
            base_threads = base_threads.exclude(id__in=bin_thread_ids)
            
            
        deleted_states = (
            MessageThreadState.objects
            .filter(
                user=user,
                deleted_at__isnull=False,
            )
            .values(
                "thread_id",
                "deleted_at",
            )
        )

        for deleted_state in deleted_states:
            has_new_incoming_message = (
                Message.objects
                .filter(
                    thread_id=deleted_state["thread_id"],
                    created__gt=deleted_state["deleted_at"],
                    message_type=Message.TYPE_TEXT,
                )
                .exclude(sender=user)
                .filter(
                    Q(metadata__system_event__isnull=True)
                    | Q(metadata__system_event=False)
                )
                .exists()
            )

            if not has_new_incoming_message:
                base_threads = base_threads.exclude(
                    id=deleted_state["thread_id"]
                )    

        # Good-fit threads
        good_fit_ids = MessageThreadState.objects.filter(
            user=user,
            label="good_fit",
            in_bin=False,
        ).values_list("thread_id", flat=True)

        good_fit_threads = base_threads.filter(id__in=good_fit_ids)

        # Counts
        total_threads = base_threads.distinct().count()
        total_good_fit = good_fit_threads.distinct().count()

        # Keep stats consistent with the thread-list unread rule:
        # system events or messages from the other participant remain
        # unread until this user reads them.
        
        hidden_by_delete = MessageThreadState.objects.filter(
            user=user,
            thread_id=OuterRef("thread_id"),
            deleted_at__isnull=False,
            deleted_at__gte=OuterRef("created"),
        )
        
        
        
        total_unread = (
            Message.objects
            .filter(thread__in=base_threads)
            .annotate(
                hidden_by_delete=Exists(hidden_by_delete)
            )
            .filter(hidden_by_delete=False)
            .filter(
                Q(metadata__system_event=True)
                | ~Q(sender=user)
            )
            .exclude(reads__user=user)
            .distinct()
            .count()
        )

        good_fit_unread = (
            Message.objects
            .filter(thread__in=good_fit_threads)
            .annotate(
                hidden_by_delete=Exists(hidden_by_delete)
            )
            .filter(hidden_by_delete=False)
            .filter(
                Q(metadata__system_event=True)
                | ~Q(sender=user)
            )
            .exclude(reads__user=user)
            .distinct()
            .count()
        )

        return Response(
            {
                "total_threads": total_threads,
                "total_unread": total_unread,
                "good_fit": {
                    "threads": total_good_fit,
                    "unread": good_fit_unread,
                },
            },
            status=status.HTTP_200_OK,
        )





class MessageListCreateView(generics.ListCreateAPIView):

    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardLimitOffsetPagination
    throttle_classes = [MessageUserThrottle]

    def get_throttles(self):
        # Only throttle sending messages (POST), not reading (GET),
        # so pagination/security tests donâ€™t get random 429s.
        if self.request.method == "POST":
            return super().get_throttles()
        return []

    # NEW: allow ?ordering=created / -created / updated / -updated / id / -id
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["updated", "created", "id"]
    ordering = ["-created"]

    def get_queryset(self):
        thread_id = self.kwargs["thread_id"]
        user = self.request.user

        # HARD GUARD: user must be a participant (otherwise 404)
        get_object_or_404(
            _role_scoped_threads(user),
            id=thread_id,
        )

        qs = Message.objects.filter(thread__id=thread_id).order_by("-created")
        deleted_at = (
            MessageThreadState.objects
            .filter(
                user=user,
                thread_id=thread_id,
            )
            .values_list("deleted_at", flat=True)
            .first()
        )

        if deleted_at is not None:
            qs = qs.filter(created__gt=deleted_at)

        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(body__icontains=q)

        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return MessageCreateSerializer
        return MessageSerializer

    def perform_create(self, serializer):
        thread = get_object_or_404(
            _role_scoped_threads(self.request.user),
            id=self.kwargs["thread_id"]
        )
        serializer.save(thread=thread, sender=self.request.user)

    @extend_schema(
        responses={
            200: inline_serializer(
                name="PaginatedThreadMessageListOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": MessageSerializer(many=True),
                    "meta": inline_serializer(
                        name="ThreadMessageListMeta",
                        fields={
                            "count": serializers.IntegerField(),
                            "next": serializers.CharField(required=False, allow_null=True),
                            "previous": serializers.CharField(required=False, allow_null=True),
                        },
                    ),
                    "count": serializers.IntegerField(required=False, allow_null=True),
                    "next": serializers.CharField(required=False, allow_null=True),
                    "previous": serializers.CharField(required=False, allow_null=True),
                    "results": MessageSerializer(many=True, required=False),
                },
            )
        },
        parameters=[
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of messages to return.",
            ),
            OpenApiParameter(
                name="offset",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of messages to skip before starting the result set.",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Sort messages by created, -created, updated, -updated, id, or -id.",
            ),
            OpenApiParameter(
                name="q",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search in message body.",
            ),
        ],
        description="List messages in a thread wrapped in ok_response. Supports pagination, ordering, and search.",
    )
    def list(self, request, *args, **kwargs):
        resp = super().list(request, *args, **kwargs)

        if isinstance(resp.data, dict) and "results" in resp.data:
            meta = {
                "count": resp.data.get("count"),
                "next": resp.data.get("next"),
                "previous": resp.data.get("previous"),
            }
            return ok_response(resp.data.get("results"), meta=meta, status_code=resp.status_code)

        return ok_response(resp.data, status_code=resp.status_code)

    @extend_schema(
        request=MessageCreateSerializer,
        responses={
            201: standard_response_serializer(
                "ThreadMessageCreateResponse",
                MessageSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
            401: OpenApiResponse(response=ErrorResponseSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
            429: OpenApiResponse(response=ErrorResponseSerializer),
        },
        description="Create a new message in a thread the authenticated user participates in.",
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        message = Message.objects.get(pk=serializer.instance.pk)

        return ok_response(
            MessageSerializer(message, context=self.get_serializer_context()).data,
            message="Message created successfully.",
            status_code=status.HTTP_201_CREATED,
        )






class ThreadMarkReadView(APIView):
    """POST /api/messages/threads/<thread_id>/read/ â€” marks all inbound messages as read."""
    permission_classes = [IsAuthenticated]
    # Disable throttling here as well to avoid flakiness
    # throttle_classes = [UserRateThrottle]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="ThreadMarkReadOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="ThreadMarkReadData",
                        fields={
                            "marked": serializers.IntegerField(),
                            "thread_unread_count": serializers.IntegerField(),
                            "account_unread_total": serializers.IntegerField(),
                        },
                    ),
                },
            ),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Thread not found."),
        },
        description="Mark thread as read for the current user.",
    )
    def post(self, request, thread_id):
        thread = get_object_or_404(
            _role_scoped_threads(request.user),
            pk=thread_id,
        )

        

        # A normal human message is inbound when someone else sent it.
        #
        # A RentCrib system message is addressed to the thread participants
        # regardless of which real user had to be stored in Message.sender.
        #
        # Therefore system_event messages must be markable as read by BOTH
        # participants, including the user whose id happens to be in sender_id.
        
        deleted_at = (
            MessageThreadState.objects
            .filter(
                user=request.user,
                thread=thread,
            )
            .values_list("deleted_at", flat=True)
            .first()
        )

        visible_messages = thread.messages.all()

        if deleted_at is not None:
            visible_messages = visible_messages.filter(
                created__gt=deleted_at
            )
        
        
        messages_to_mark = list(
            visible_messages
            .filter(
                Q(metadata__system_event=True)
                | ~Q(sender=request.user)
            )
            .exclude(reads__user=request.user)
            .distinct()
        )

        MessageRead.objects.bulk_create(
            [
                MessageRead(
                    message=message,
                    user=request.user,
                )
                for message in messages_to_mark
            ],
            ignore_conflicts=True,
        )

        # Only genuine human messages produce read receipts back to their
        # original sender. RentCrib system events do not have a meaningful
        # human sender even though the model requires one.
        message_ids_by_sender = {}

        for message in messages_to_mark:
            metadata = message.metadata or {}

            if metadata.get("system_event") is True:
                continue

            message_ids_by_sender.setdefault(
                message.sender_id,
                [],
            ).append(message.id)

        for sender_id, message_ids in message_ids_by_sender.items():
            push_user_realtime_event(
                sender_id,
                "message_read",
                {
                    "thread_id": thread.id,
                    "reader_id": request.user.id,
                    "message_ids": message_ids,
                },
            )

        # Calculate the global unread-envelope count using exactly the same rule:
        #
        # - normal messages count when another user sent them
        # - system_event messages count for every participant until that
        #   participant has their own MessageRead row
        base_threads = _role_scoped_threads(request.user)

        bin_thread_ids = list(
            MessageThreadState.objects
            .filter(
                user=request.user,
                in_bin=True,
            )
            .values_list(
                "thread_id",
                flat=True,
            )
        )

        if bin_thread_ids:
            base_threads = base_threads.exclude(
                id__in=bin_thread_ids,
            )

        hidden_by_delete = MessageThreadState.objects.filter(
            user=request.user,
            thread_id=OuterRef("thread_id"),
            deleted_at__isnull=False,
            deleted_at__gte=OuterRef("created"),
        )
        
        
        total_unread = (
            Message.objects
            .filter(thread__in=base_threads)
            .annotate(
                hidden_by_delete=Exists(hidden_by_delete)
            )
            .filter(hidden_by_delete=False)
            .filter(
                Q(metadata__system_event=True)
                | ~Q(sender=request.user)
            )
            .exclude(reads__user=request.user)
            .distinct()
            .count()
        )

        push_user_realtime_event(
            request.user.id,
            "unread_count_changed",
            {
                "thread_id": thread.id,
                "thread_unread_count": 0,
                "account_unread_total": total_unread,
            },
        )

        return ok_response(
            {
                "marked": len(messages_to_mark),
                "thread_unread_count": 0,
                "account_unread_total": total_unread,
            },
            status_code=status.HTTP_200_OK,
        )
        
        
class ThreadsBulkMarkReadView(APIView):
    """
    POST /api/v1/messages/threads/read/

    Mark multiple message threads as read for the authenticated user.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        thread_ids = request.data.get("thread_ids") or []

        if not isinstance(thread_ids, list) or not thread_ids:
            raise ValidationError(
                {"thread_ids": "Provide a non-empty list of thread ids."}
            )

        try:
            thread_ids = list({int(thread_id) for thread_id in thread_ids})
        except (TypeError, ValueError):
            raise ValidationError(
                {"thread_ids": "All thread ids must be integers."}
            )

        threads = list(
            _role_scoped_threads(request.user)
            .filter(
                id__in=thread_ids,
            )
            .distinct()
        )

        found_ids = {thread.id for thread in threads}
        missing_ids = sorted(set(thread_ids) - found_ids)

        if missing_ids:
            raise ValidationError(
                {
                    "thread_ids": (
                        "One or more threads do not exist or do not belong "
                        f"to this user: {missing_ids}"
                    )
                }
            )

        hidden_by_delete = MessageThreadState.objects.filter(
            user=request.user,
            thread_id=OuterRef("thread_id"),
            deleted_at__isnull=False,
            deleted_at__gte=OuterRef("created"),
        )




        messages_to_mark = list(
            Message.objects
            .filter(thread__in=threads)
            .annotate(
                hidden_by_delete=Exists(hidden_by_delete)
            )
            .filter(hidden_by_delete=False)
            .filter(
                Q(metadata__system_event=True)
                | ~Q(sender=request.user)
            )
            .exclude(reads__user=request.user)
            .distinct()
        )

        MessageRead.objects.bulk_create(
            [
                MessageRead(
                    message=message,
                    user=request.user,
                )
                for message in messages_to_mark
            ],
            ignore_conflicts=True,
        )

        message_ids_by_sender_and_thread = {}

        for message in messages_to_mark:
            metadata = message.metadata or {}

            if metadata.get("system_event") is True:
                continue

            key = (message.sender_id, message.thread_id)

            message_ids_by_sender_and_thread.setdefault(
                key,
                [],
            ).append(message.id)

        for (sender_id, thread_id), message_ids in message_ids_by_sender_and_thread.items():
            push_user_realtime_event(
                sender_id,
                "message_read",
                {
                    "thread_id": thread_id,
                    "reader_id": request.user.id,
                    "message_ids": message_ids,
                },
            )

        base_threads = _role_scoped_threads(request.user)

        bin_thread_ids = list(
            MessageThreadState.objects
            .filter(
                user=request.user,
                in_bin=True,
            )
            .values_list(
                "thread_id",
                flat=True,
            )
        )

        if bin_thread_ids:
            base_threads = base_threads.exclude(
                id__in=bin_thread_ids,
            )
            
            
        hidden_by_delete = MessageThreadState.objects.filter(
            user=request.user,
            thread_id=OuterRef("thread_id"),
            deleted_at__isnull=False,
            deleted_at__gte=OuterRef("created"),
        )     
            
        total_unread = (
            Message.objects
            .filter(thread__in=base_threads)
            .annotate(
                hidden_by_delete=Exists(hidden_by_delete)
            )
            .filter(hidden_by_delete=False)
            .filter(
                Q(metadata__system_event=True)
                | ~Q(sender=request.user)
            )
            .exclude(reads__user=request.user)
            .distinct()
            .count()
        )

        push_user_realtime_event(
            request.user.id,
            "unread_count_changed",
            {
                "thread_ids": thread_ids,
                "thread_unread_counts": {
                    str(thread_id): 0
                    for thread_id in thread_ids
                },
                "account_unread_total": total_unread,
            },
        )

        return ok_response(
            {
                "marked": len(messages_to_mark),
                "thread_ids": thread_ids,
                "account_unread_total": total_unread,
            },
            status_code=status.HTTP_200_OK,
        )        


class ThreadDeleteForeverView(APIView):
    """
    POST /api/v1/messages/threads/<thread_id>/delete/

    Permanently delete a message thread for the authenticated user only.

    This does not delete the shared MessageThread or the other participant's
    history. It records a per-user deletion cutoff. Messages created at or
    before deleted_at are hidden from this user.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, thread_id):
        thread = get_object_or_404(
            _role_scoped_threads(request.user),
            id=thread_id,
        )

        state, _ = MessageThreadState.objects.get_or_create(
            user=request.user,
            thread=thread,
        )

        state.deleted_at = timezone.now()
        state.in_bin = False
        state.save(update_fields=["deleted_at", "in_bin", "updated_at"])

        return Response(
            {
                "thread_id": thread.id,
                "deleted": True,
                "deleted_at": state.deleted_at,
            },
            status=status.HTTP_200_OK,
        )


class ThreadsBulkDeleteForeverView(APIView):
    """
    POST /api/v1/messages/threads/delete/

    Permanently delete multiple message threads for the authenticated user.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        thread_ids = request.data.get("thread_ids") or []

        if not isinstance(thread_ids, list) or not thread_ids:
            raise ValidationError(
                {"thread_ids": "Provide a non-empty list of thread ids."}
            )

        try:
            thread_ids = list({int(thread_id) for thread_id in thread_ids})
        except (TypeError, ValueError):
            raise ValidationError(
                {"thread_ids": "All thread ids must be integers."}
            )

        threads = list(
            _role_scoped_threads(request.user)
            .filter(id__in=thread_ids)
            .distinct()
        )

        found_ids = {thread.id for thread in threads}
        missing_ids = sorted(set(thread_ids) - found_ids)

        if missing_ids:
            raise ValidationError(
                {
                    "thread_ids": (
                        "One or more threads do not exist or do not belong "
                        f"to this user: {missing_ids}"
                    )
                }
            )

        deleted_at = timezone.now()

        existing_states = {
            state.thread_id: state
            for state in MessageThreadState.objects.filter(
                user=request.user,
                thread_id__in=thread_ids,
            )
        }

        states_to_create = []
        states_to_update = []

        for thread in threads:
            state = existing_states.get(thread.id)

            if state is None:
                states_to_create.append(
                    MessageThreadState(
                        user=request.user,
                        thread=thread,
                        deleted_at=deleted_at,
                        in_bin=False,
                    )
                )
            else:
                state.deleted_at = deleted_at
                state.in_bin = False
                state.updated_at = deleted_at
                states_to_update.append(state)

        if states_to_create:
            MessageThreadState.objects.bulk_create(states_to_create)

        if states_to_update:
            MessageThreadState.objects.bulk_update(
                states_to_update,
                ["deleted_at", "in_bin", "updated_at"],
            )

        return Response(
            {
                "thread_ids": sorted(thread_ids),
                "deleted": len(thread_ids),
                "deleted_at": deleted_at,
            },
            status=status.HTTP_200_OK,
        )




class ThreadSetLabelView(APIView):
    """
    POST /api/messages/threads/<thread_id>/label/
    Body: {"label": "viewing_scheduled" | "viewing_done" | "good_fit" | "unsure" | "not_a_fit" | "paperwork_pending" | "none"}

    Per-user label for a thread (used by the â€œFilter by labelâ€ dropdown).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ThreadSetLabelRequestSerializer,
        responses={
            200: inline_serializer(
                name="ThreadSetLabelResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="ThreadSetLabelData",
                        fields={
                            "thread_id": serializers.IntegerField(),
                            "label": serializers.CharField(required=False, allow_null=True),
                        },
                    ),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Thread not found."),
        },
        description="Set per-user label for a message thread.",
    )
    def post(self, request, thread_id):
        # Only allow labels for threads I am in
        thread = get_object_or_404(
            _role_scoped_threads(request.user),
            pk=thread_id,
        )

        raw_label = (request.data.get("label") or "").strip()

        # Map the allowed incoming values to what we actually store
        # (here they are the same strings, except "none" => "")
        allowed = {
            "none": "",
            "viewing_scheduled": "viewing_scheduled",
            "viewing_done": "viewing_done",
            "good_fit": "good_fit",
            "unsure": "unsure",
            "not_a_fit": "not_a_fit",
            "paperwork_pending": "paperwork_pending",
        }

        if raw_label not in allowed:
            return Response(
                {
                    "label": "Invalid label. Use one of: "
                             "none, viewing_scheduled, viewing_done, good_fit, "
                             "unsure, not_a_fit, paperwork_pending."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get or create per-user state row
        state, _ = MessageThreadState.objects.get_or_create(
            user=request.user,
            thread=thread,
        )

        state.label = allowed[raw_label]
        state.save(update_fields=["label", "updated_at"])

        return ok_response(
            {
                "thread_id": thread.id,
                "label": state.label or None,
            },
            status_code=status.HTTP_200_OK,
        )




class ThreadMoveToBinView(APIView):
    """
    POST /api/messages/threads/<thread_id>/bin/
    Move this thread into the current user's Bin.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ThreadMoveToBinRequestSerializer,
        responses={
            200: inline_serializer(
                name="ThreadMoveToBinResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="ThreadMoveToBinData",
                        fields={"detail": serializers.CharField()},
                    ),
                },
            ),
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Thread not found."),
        },
        description="Move a thread to bin (per-user).",
    )
    def post(self, request, thread_id):
        thread = get_object_or_404(
            _role_scoped_threads(request.user),
            pk=thread_id,
        )

        state, _ = MessageThreadState.objects.get_or_create(
            user=request.user,
            thread=thread,
        )

        if not state.in_bin:
            state.in_bin = True
            state.save(update_fields=["in_bin", "updated_at"])

        return ok_response(
            {"detail": "Thread moved to bin."},
            status_code=status.HTTP_200_OK,
        )





class ThreadRestoreFromBinView(APIView):
    """
    POST /api/messages/threads/<thread_id>/restore/
    Restore this thread from the current user's Bin back to the inbox.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="ThreadRestoreFromBinResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": inline_serializer(
                        name="ThreadRestoreFromBinData",
                        fields={
                            "id": serializers.IntegerField(),
                            "in_bin": serializers.BooleanField(),
                        },
                    ),
                },
            ),
            401: OpenApiResponse(description="Authentication required."),
            404: OpenApiResponse(description="Thread not found."),
        },
        description="Restore a thread from bin back to inbox (per-user).",
    )
    def post(self, request, thread_id):
        thread = get_object_or_404(
            _role_scoped_threads(request.user),
            pk=thread_id,
        )

        try:
            state = MessageThreadState.objects.get(user=request.user, thread=thread)
        except MessageThreadState.DoesNotExist:
            # Nothing to restore; treat as already in inbox
            return ok_response(
                {"id": thread.id, "in_bin": False},
                status_code=status.HTTP_200_OK,
            )

        if state.in_bin:
            state.in_bin = False
            state.save(update_fields=["in_bin", "updated_at"])

        return ok_response(
            {"id": thread.id, "in_bin": False},
            status_code=status.HTTP_200_OK,
        )




class StartThreadFromRoomView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=inline_serializer(
            name="StartThreadFromRoomRequest",
            fields={
                "body": serializers.CharField(required=False, allow_blank=True),
            },
        ),
        responses={
            200: inline_serializer(
                name="StartThreadFromRoomOkResponse",
                fields={
                    "ok": serializers.BooleanField(),
                    "message": serializers.CharField(required=False, allow_null=True),
                    "data": MessageThreadSerializer(),
                },
            ),
            400: DetailResponseSerializer,
            401: OpenApiResponse(description="Authentication required."),
            404: DetailResponseSerializer,
        },
        description="Start or reuse a message thread from a room, and optionally send an initial message.",
    )
    def post(self, request, room_id):
        room = get_object_or_404(Room.objects.alive(), pk=room_id)

        if room.property_owner == request.user:
            return Response(
                {"detail": "You are the owner of this room; no thread needed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        thread = get_or_create_canonical_thread(
            landlord=room.property_owner,
            seeker=request.user,
            room=room,
        )
        body = (request.data or {}).get("body", "").strip()
        if body:
            Message.objects.create(thread=thread, sender=request.user, body=body)

        return ok_response(
            MessageThreadSerializer(thread, context={"request": request}).data,
            status_code=status.HTTP_200_OK,
        )




class ContactMessageCreateView(generics.CreateAPIView):
    """
    Public Contact Us endpoint.
    Used by the Contact Us form on the marketing site.
    """
    permission_classes = [AllowAny]
    serializer_class = ContactMessageSerializer

    @extend_schema(
        request=ContactMessageSerializer,
        responses={
            201: standard_response_serializer(
                "ContactMessageCreateResponse",
                ContactMessageSerializer,
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {
                    "ok": False,
                    "message": "Validation error.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        self.perform_create(serializer)
        response = ok_response(
            serializer.data,
            message="Contact message submitted successfully.",
            status_code=status.HTTP_201_CREATED,
        )

        headers = self.get_success_headers(serializer.data)
        for key, value in headers.items():
            response[key] = value

        return response


class ThreadMoveToBinRequestSerializer(serializers.Serializer):
    # Body is optional for this endpoint, but spectacular needs a serializer
    pass

class ThreadSetLabelRequestSerializer(serializers.Serializer):
    label = serializers.ChoiceField(
        choices=[
            "none",
            "viewing_scheduled",
            "viewing_done",
            "good_fit",
            "unsure",
            "not_a_fit",
            "paperwork_pending",
        ]
    )

class ThreadMarkReadRequestSerializer(serializers.Serializer):
    # If your endpoint marks the whole thread read, no body needed.
    # Keep as empty serializer for schema.
    pass











