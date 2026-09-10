"""Query optimization for message-thread list filtering."""

from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, IntegerField, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError

from propertylist_app.api.views.messaging import MessageThreadListCreateView
from propertylist_app.models import Message, MessageThread, MessageThreadState, UserProfile


_INSTALLED = False


def _optimized_get_queryset(self):
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
        .annotate(hidden_by_delete=Exists(hidden_by_delete))
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

    profile, _ = UserProfile.objects.get_or_create(user=user)
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

    # Keep the existing restore-after-new-message behaviour, but express it
    # as correlated SQL instead of issuing one Message.exists() query for
    # every deleted thread state.
    deleted_at_for_user = (
        MessageThreadState.objects
        .filter(
            user=user,
            thread_id=OuterRef("pk"),
            deleted_at__isnull=False,
        )
        .values("deleted_at")[:1]
    )

    qs = qs.annotate(
        _deleted_at_for_user=Subquery(deleted_at_for_user),
    )

    new_incoming_after_delete = (
        Message.objects
        .filter(
            thread_id=OuterRef("pk"),
            created__gt=OuterRef("_deleted_at_for_user"),
            message_type=Message.TYPE_TEXT,
        )
        .exclude(sender=user)
        .filter(
            Q(metadata__system_event__isnull=True)
            | Q(metadata__system_event=False)
        )
    )

    qs = (
        qs.annotate(
            _has_new_incoming_after_delete=Exists(new_incoming_after_delete),
        )
        .filter(
            Q(_deleted_at_for_user__isnull=True)
            | Q(_has_new_incoming_after_delete=True)
        )
    )

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
                .annotate(hidden_by_delete=Exists(hidden_by_delete))
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


def install_message_thread_query_optimization():
    """Install the optimized message-thread queryset once at startup."""
    global _INSTALLED

    if _INSTALLED:
        return

    MessageThreadListCreateView.get_queryset = _optimized_get_queryset
    _INSTALLED = True
