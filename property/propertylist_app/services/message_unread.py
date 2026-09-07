from django.db.models import Exists, OuterRef, Q


def system_message_unread_payload(
    user_id: int,
    data: dict,
) -> dict | None:
    """
    Return authoritative envelope counts for one RentCrib system message.

    Ordinary human chat messages already publish ``unread_count_changed`` from
    the Message post-save signal. RentCrib workflow/system messages deliberately
    bypass that signal and are emitted manually, so they need one shared
    fallback instead of every workflow reimplementing the envelope counter.

    These visibility rules mirror MessageStatsView:
    - only the user's active landlord/seeker role counts;
    - binned conversations do not count;
    - a permanently deleted conversation stays hidden until a genuine incoming
      human message arrives after the delete cutoff;
    - system events count for both participants until that participant has a
      MessageRead row, regardless of which participant is stored in sender FK.
    """
    message_id = data.get("message_id")
    thread_id = data.get("thread_id")

    if message_id is None or thread_id is None:
        return None

    # Local imports keep this helper out of the model import graph at process
    # start-up; it only runs after a persisted realtime message is committed.
    from propertylist_app.models import (
        Message,
        MessageThread,
        MessageThreadState,
        UserProfile,
    )

    if not Message.objects.filter(
        pk=message_id,
        thread_id=thread_id,
        metadata__system_event=True,
    ).exists():
        return None

    profile, _ = UserProfile.objects.get_or_create(
        user_id=user_id,
    )

    base_threads = MessageThread.objects.filter(
        participants=user_id,
    )

    if profile.role == "landlord":
        base_threads = base_threads.filter(
            Q(landlord_id=user_id)
            | Q(
                landlord__isnull=True,
                seeker__isnull=True,
            )
        )
    else:
        base_threads = base_threads.filter(
            Q(seeker_id=user_id)
            | Q(
                landlord__isnull=True,
                seeker__isnull=True,
            )
        )

    bin_thread_ids = list(
        MessageThreadState.objects
        .filter(
            user_id=user_id,
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

    # Permanent delete is per-user. A workflow/system event alone must not
    # resurrect a deleted conversation; only a genuine incoming human message
    # after the cutoff restores it.
    deleted_states = (
        MessageThreadState.objects
        .filter(
            user_id=user_id,
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
            .exclude(sender_id=user_id)
            .filter(
                Q(metadata__system_event__isnull=True)
                | Q(metadata__system_event=False)
            )
            .exists()
        )

        if not has_new_incoming_message:
            base_threads = base_threads.exclude(
                id=deleted_state["thread_id"],
            )

    hidden_by_delete = MessageThreadState.objects.filter(
        user_id=user_id,
        thread_id=OuterRef("thread_id"),
        deleted_at__isnull=False,
        deleted_at__gte=OuterRef("created"),
    )

    unread_messages = (
        Message.objects
        .annotate(
            hidden_by_delete=Exists(hidden_by_delete),
        )
        .filter(hidden_by_delete=False)
        .filter(
            Q(metadata__system_event=True)
            | ~Q(sender_id=user_id)
        )
        .exclude(reads__user_id=user_id)
        .distinct()
    )

    if base_threads.filter(pk=thread_id).exists():
        thread_unread_count = unread_messages.filter(
            thread_id=thread_id,
        ).count()
    else:
        thread_unread_count = 0

    account_unread_total = unread_messages.filter(
        thread__in=base_threads,
    ).count()

    return {
        "thread_id": int(thread_id),
        "thread_unread_count": thread_unread_count,
        "account_unread_total": account_unread_total,
    }
