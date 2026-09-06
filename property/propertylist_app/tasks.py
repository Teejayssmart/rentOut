from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q, F
from django.apps import apps
from django.conf import settings
from datetime import timedelta
from propertylist_app.services.tenancy_chat import post_tenancy_event
from propertylist_app.services.realtime import push_user_realtime_event
from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.models import (
    UserProfile,
    Room,
    Review,
    MessageThreadState,
    MessageThread,
    Message,
    Booking,
)

from propertylist_app.services.tasks import (
    send_new_message_email,
    expire_paid_listings,
)
from propertylist_app.services.tenancy_dates import (
    compute_end_date,
    compute_review_window,
)


# from propertylist_app.services.reviews import update_room_rating_from_revealed_reviews

# IMPORTANT: ensure nested notification tasks are registered
# from propertylist_app.notifications.tasks import notify_completed_viewings  # noqa: F401

from django.db.models import Avg, Count

from celery import shared_task



# -------------------------------------------------------------------
# Celery decorator (safe fallback for tests)
# -------------------------------------------------------------------
try:
    from celery import shared_task
except Exception:  # pragma: no cover
    def shared_task(*args, **kwargs):
        def wrapper(fn):
            fn.delay = fn
            return fn
        return wrapper


# -------------------------------------------------------------------
# Messaging / listings
# -------------------------------------------------------------------
@shared_task(name="propertylist_app.send_new_message_email")
def task_send_new_message_email(message_id: int) -> int:
    return send_new_message_email(message_id)


@shared_task(name="propertylist_app.expire_paid_listings")
def task_expire_paid_listings() -> int:
    return expire_paid_listings()


# -------------------------------------------------------------------
# Account deletion
# -------------------------------------------------------------------
@shared_task(name="propertylist_app.delete_scheduled_accounts")
def task_delete_scheduled_accounts() -> int:
    now = timezone.now()
    UserModel = get_user_model()

    profiles = (
        UserProfile.objects
        .filter(pending_deletion_scheduled_for__isnull=False)
        .filter(pending_deletion_scheduled_for__lte=now)
        .select_related("user")
    )

    deleted = 0
    for profile in profiles:
        user = profile.user
        if not user:
            profile.pending_deletion_requested_at = None
            profile.pending_deletion_scheduled_for = None
            profile.save(
                update_fields=[
                    "pending_deletion_requested_at",
                    "pending_deletion_scheduled_for",
                ]
            )
            continue

        UserModel.objects.filter(pk=user.pk).delete()
        deleted += 1

    return deleted


# -------------------------------------------------------------------
# Nightly room rating refresh (double-blind safe)
# -------------------------------------------------------------------
@shared_task(name="propertylist_app.refresh_room_ratings_nightly")
def task_refresh_room_ratings_nightly() -> int:
    from propertylist_app.signals import _recalc_room_rating

    now = timezone.now()

    rooms = Room.objects.filter(
    Exists(
        Review.objects.filter(
            Q(tenancy__room=OuterRef("pk")) | Q(tenancy__room=OuterRef("pk")),
            role=Review.ROLE_TENANT_TO_LANDLORD,
            active=True,
            reveal_at__isnull=False,
            reveal_at__lte=now,
        )
    )
    )


    count = 0
    for room in rooms:
        _recalc_room_rating(room)
        count += 1

    return count


def _queue_email(*, user, template_key: str, context: dict | None = None) -> None:
    """
    Queue an email via notifications pipeline.
    Only queues if an active email template exists for the key.
    """
    template = NotificationTemplate.objects.filter(
        key=template_key,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        is_active=True,
    ).first()
    if not template:
        return

    OutboundNotification.objects.create(
        user=user,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key=template_key,
        context=context or {},
    )



# -------------------------------------------------------------------
# Tenancy notifications (INBOX ONLY – stable)
# -------------------------------------------------------------------

@shared_task
def task_send_tenancy_notification(tenancy_id: int, event: str) -> int:
    Tenancy = apps.get_model("propertylist_app", "Tenancy")
    Notification = apps.get_model("propertylist_app", "Notification")
    UserProfile = apps.get_model("propertylist_app", "UserProfile")

    supported_events = {
        "proposed",
        "updated",
        "confirmed",
        "cancelled",
        "expired_unverified",
        "rejected_unverified",
    }

    if event not in supported_events:
        return 0

    tenancy = (
        Tenancy.objects
        .select_related(
            "room",
            "landlord",
            "tenant",
            "proposed_by",
        )
        .filter(id=tenancy_id)
        .first()
    )

    if not tenancy:
        return 0

    room_title = getattr(tenancy.room, "title", "your room")

    # For a new proposal or counter-proposal, proposed_by is the person
    # who submitted the current tenancy terms.
    if event in {"proposed", "updated"}:
        sender = tenancy.proposed_by

    # Confirmation or cancellation is performed by the person reviewing
    # the current proposal, which is the opposite party to proposed_by.
    elif tenancy.proposed_by_id == tenancy.tenant_id:
        sender = tenancy.landlord
    else:
        sender = tenancy.tenant

    if sender is None:
        return 0

    thread, message = post_tenancy_event(
        tenancy=tenancy,
        event_type=event,
        sender=sender,
    )

   # Mobile app deep link.
    thread_deep_link = f"/app/threads/{thread.id}"

    # Web/Vercel route used by email action buttons.
    thread_cta_url = build_absolute_url(
        f"/messages?thread={thread.id}"
    )

    def _maybe_queue(user, template_key: str, extra_context: dict | None = None):
        profile, _ = UserProfile.objects.get_or_create(user=user)

        if not getattr(profile, "notify_confirmations", True):
            return

        email_context = {
            "user": {
                "first_name": user.first_name,
            },
            "tenancy_id": tenancy.id,
            "thread_id": thread.id,
            "message_id": message.id,
            "room_title": room_title,
            "move_in_date": (
                tenancy.move_in_date.isoformat()
                if tenancy.move_in_date
                else None
            ),
            "duration_months": tenancy.duration_months,
            "monthly_rent": (
                str(tenancy.room.price_per_month)
                if tenancy.room.price_per_month is not None
                else None
            ),
            "deep_link": thread_deep_link,
            "cta_url": thread_cta_url,
        }

        if extra_context:
            email_context.update(extra_context)

        _queue_email(
            user=user,
            template_key=template_key,
            context=email_context,
        )

    def _create_notification(
        *,
        user,
        notification_type: str,
        title: str,
        body: str,
        audience: str = Notification.Audience.BOTH,
        target_type: str = "message",
        target_id=None,
    ):
        # Important tenancy actions must return the conversation to Inbox.
        thread_state, _ = MessageThreadState.objects.get_or_create(
            user=user,
            thread=thread,
        )

        if thread_state.in_bin or thread_state.label:
            thread_state.in_bin = False
            thread_state.label = ""
            thread_state.save(
                update_fields=[
                    "in_bin",
                    "label",
                    "updated_at",
                ]
            )

        notification, notification_created = (
            Notification.objects.get_or_create(
                user=user,
                type=notification_type,
                target_type=target_type,
                target_id=(
                    target_id
                    if target_id is not None
                    else message.id
                ),
                defaults={
                    "thread": thread,
                    "message": message,
                    "audience": audience,
                    "title": title,
                    "body": body,
                },
            )
        )

        if notification_created:
            push_user_realtime_event(
                user.id,
                "new_message",
                {
                    "message_id": message.id,
                    "thread_id": thread.id,
                    "sender_id": message.sender_id,
                },
            )

            push_user_realtime_event(
                user.id,
                "new_notification",
                {
                    "kind": notification_type,
                    "notification_id": notification.id,
                    "message_id": message.id,
                    "thread_id": thread.id,
                },
            )

    if event == "proposed":
        tenant_submitted_first = sender.id == tenancy.tenant_id

        target_user = (
            tenancy.landlord
            if tenant_submitted_first
            else tenancy.tenant
        )
        target_audience = (
            Notification.Audience.LANDLORD
            if tenant_submitted_first
            else Notification.Audience.SEEKER
        )

        sender_name = (
            sender.get_full_name().strip()
            or sender.username
        )

        if tenant_submitted_first:
            notification_title = "Verify tenancy claim"
            notification_body = (
                f"{sender_name} says they rented {room_title}. "
                "Confirm that you actually rented the room to this person "
                "before agreeing."
            )
        else:
            notification_title = "Review tenancy information"
            notification_body = (
                f"Your landlord submitted tenancy information for "
                f"{room_title}. Please review it."
            )

        _create_notification(
            user=target_user,
            notification_type="tenancy_proposed",
            title=notification_title,
            body=notification_body,
            audience=target_audience,
            target_type="tenancy",
            target_id=tenancy.id,
        )

        _maybe_queue(
            target_user,
            "tenancy.proposed",
            {
                "sender_name": sender_name,
                "tenant_name": (
                    tenancy.tenant.get_full_name().strip()
                    or tenancy.tenant.username
                ),
                "landlord_name": (
                    tenancy.landlord.get_full_name().strip()
                    or tenancy.landlord.username
                ),
                "tenant_submitted_first": tenant_submitted_first,
            },
        )

        return 1

    if event == "confirmed":
        # Use the existing tenancy conversation so the confirmation bell
        # opens the exact conversation associated with this tenancy.
        tenancy_message = (
            Message.objects
            .select_related("thread")
            .filter(metadata__tenancy_id=tenancy.id)
            .order_by("-created")
            .first()
        )

        confirmation_thread = (
            tenancy_message.thread
            if tenancy_message and tenancy_message.thread_id
            else None
        )

        for user, audience in (
            (tenancy.landlord, Notification.Audience.LANDLORD),
            (tenancy.tenant, Notification.Audience.SEEKER),
        ):

            notification = Notification.objects.create(
                user=user,
                type="tenancy_confirmed",
                target_type="tenancy",
                target_id=tenancy.id,
                thread=confirmation_thread,
                message=tenancy_message,
                title="Tenancy confirmed",
                body=f"Tenancy confirmed for: {room_title}.",
                audience=audience,
            )

            push_user_realtime_event(
                user.id,
                "new_notification",
                {
                    "kind": "tenancy_confirmed",
                    "notification_id": notification.id,
                    "tenancy_id": tenancy.id,
                    "thread_id": (
                        confirmation_thread.id
                        if confirmation_thread
                        else None
                    ),
                    "message_id": (
                        tenancy_message.id
                        if tenancy_message
                        else None
                    ),
                },
            )
            
            # Tenancy confirmation is also an Inbox/envelope event.
            # Structured tenancy messages do not pass through the ordinary
            # TYPE_TEXT Message signal, so publish the message/unread events here.
            if confirmation_thread and tenancy_message:
                push_user_realtime_event(
                    user.id,
                    "new_message",
                    {
                        "message_id": tenancy_message.id,
                        "thread_id": confirmation_thread.id,
                        "sender_id": tenancy_message.sender_id,
                    },
                )

                thread_unread_count = (
                    Message.objects
                    .filter(thread=confirmation_thread)
                    .filter(
                        Q(metadata__system_event=True)
                        | ~Q(sender=user)
                    )
                    .exclude(reads__user=user)
                    .distinct()
                    .count()
                )

                if audience == Notification.Audience.LANDLORD:
                    thread_queryset = (
                        MessageThread.objects
                        .filter(participants=user)
                        .filter(
                            Q(landlord=user)
                            | Q(
                                landlord__isnull=True,
                                seeker__isnull=True,
                            )
                        )
                    )
                else:
                    thread_queryset = (
                        MessageThread.objects
                        .filter(participants=user)
                        .filter(
                            Q(seeker=user)
                            | Q(
                                landlord__isnull=True,
                                seeker__isnull=True,
                            )
                        )
                    )

                bin_thread_ids = list(
                    MessageThreadState.objects
                    .filter(
                        user=user,
                        in_bin=True,
                    )
                    .values_list(
                        "thread_id",
                        flat=True,
                    )
                )

                if bin_thread_ids:
                    thread_queryset = thread_queryset.exclude(
                        id__in=bin_thread_ids,
                    )

                account_unread_total = (
                    Message.objects
                    .filter(thread__in=thread_queryset)
                    .filter(
                        Q(metadata__system_event=True)
                        | ~Q(sender=user)
                    )
                    .exclude(reads__user=user)
                    .distinct()
                    .count()
                )

                push_user_realtime_event(
                    user.id,
                    "unread_count_changed",
                    {
                        "thread_id": confirmation_thread.id,
                        "thread_unread_count": thread_unread_count,
                        "account_unread_total": account_unread_total,
                    },
                )
            
            
            

            _maybe_queue(
                user,
                "tenancy.confirmed",
                {
                    "cta_url": build_absolute_url(
                        f"/tenancies/{tenancy.id}"
                    ),
                },
            )

        return 2
        
    
    if event == "rejected_unverified":
        tenant_name = (
            tenancy.tenant.get_full_name().strip()
            or tenancy.tenant.username
        )
        landlord_name = (
            tenancy.landlord.get_full_name().strip()
            or tenancy.landlord.username
        )

        _create_notification(
            user=tenancy.tenant,
            audience=Notification.Audience.SEEKER,
            notification_type="tenancy_rejected_unverified",
            title="Tenancy information could not be verified",
            body=(
                f"{landlord_name} could not verify the tenancy information "
                f"you submitted for {room_title}. Your submission has been "
                "cancelled."
            ),
            target_type="tenancy",
            target_id=tenancy.id,
        )

        _maybe_queue(
            tenancy.tenant,
            "tenancy.rejected_unverified",
            {
                "tenant_name": tenant_name,
                "landlord_name": landlord_name,
            },
        )

        _create_notification(
            user=tenancy.landlord,
            audience=Notification.Audience.LANDLORD,
            notification_type="tenancy_rejected_unverified",
            title="Tenancy claim rejected",
            body=(
                f"The tenancy claim submitted by {tenant_name} for "
                f"{room_title} has been rejected. The listing availability "
                "was not changed."
            ),
            target_type="tenancy",
            target_id=tenancy.id,
        )

        _maybe_queue(
            tenancy.landlord,
            "tenancy.rejected_unverified_landlord",
            {
                "tenant_name": tenant_name,
                "landlord_name": landlord_name,
            },
        )

        return 2
    
    
    if event == "expired_unverified":
        tenant_name = (
            tenancy.tenant.get_full_name().strip()
            or tenancy.tenant.username
        )

        _create_notification(
            user=tenancy.tenant,
            audience=Notification.Audience.SEEKER,
            notification_type="tenancy_expired_unverified",
            title="Tenancy request expired",
            body=(
                f"Your tenancy request for {room_title} expired because "
                "the landlord did not verify it within the required time."
            ),
            target_type="tenancy",
            target_id=tenancy.id,
        )

        _maybe_queue(
            tenancy.tenant,
            "tenancy.expired_unverified",
            {
                "tenant_name": tenant_name,
                "landlord_name": (
                    tenancy.landlord.get_full_name().strip()
                    or tenancy.landlord.username
                ),
            },
        )

        _create_notification(
            user=tenancy.landlord,
            audience=Notification.Audience.LANDLORD,
            notification_type="tenancy_expired_unverified",
            title="Unverified tenancy request expired",
            body=(
                f"The unverified tenancy request from {tenant_name} for "
                f"{room_title} has expired. The listing availability "
                "was not changed."
            ),
            target_type="tenancy",
            target_id=tenancy.id,
        )

        _maybe_queue(
            tenancy.landlord,
            "tenancy.expired_unverified_landlord",
            {
                "tenant_name": tenant_name,
                "landlord_name": (
                    tenancy.landlord.get_full_name().strip()
                    or tenancy.landlord.username
                ),
            },
        )

        return 2
    

    if event == "cancelled":
        for user, audience in (
            (
                tenancy.landlord,
                Notification.Audience.LANDLORD,
            ),
            (
                tenancy.tenant,
                Notification.Audience.SEEKER,
            ),
        ):
            _create_notification(
                user=user,
                audience=audience,
                notification_type="tenancy_cancelled",
                title="Tenancy cancelled",
                body=f"Tenancy cancelled for: {room_title}.",
                target_type="tenancy",
                target_id=tenancy.id,
            )

            _maybe_queue(
                user,
                "tenancy.cancelled",
            )

        return 2

    # updated — the one permitted correction has been submitted.
    editor = sender
    other_party = (
        tenancy.landlord
        if editor.id == tenancy.tenant_id
        else tenancy.tenant
    )

    editor_role = (
        "landlord"
        if editor.id == tenancy.landlord_id
        else "tenant"
    )
    other_party_role = (
        "tenant"
        if editor_role == "landlord"
        else "landlord"
    )
    
    editor_audience = (
        Notification.Audience.LANDLORD
        if editor_role == "landlord"
        else Notification.Audience.SEEKER
    )

    other_party_audience = (
        Notification.Audience.SEEKER
        if editor_role == "landlord"
        else Notification.Audience.LANDLORD
    )

    editor_name = editor.get_full_name().strip() or editor.username
    other_party_name = (
        other_party.get_full_name().strip()
        or other_party.username
    )

    _create_notification(
        user=editor,
        audience=editor_audience,
        notification_type="tenancy_updated",
        title="Tenancy information updated",
        body=(
            f"The tenancy information changes you made for "
            f"{room_title} have been sent to {other_party_name}."
        ),
        target_type="tenancy",
        target_id=tenancy.id,
    )

    _maybe_queue(
        editor,
        "tenancy.updated_editor",
        {
            "editor_name": editor_name,
            "editor_role": editor_role,
            "other_party_name": other_party_name,
            "other_party_role": other_party_role,
        },
    )

    _create_notification(
        user=other_party,
        audience=other_party_audience,
        notification_type="tenancy_updated",
        title="Tenancy information changed",
        body=(
            f"Your {editor_role}, {editor_name}, updated the tenancy "
            f"information for {room_title}."
        ),
        target_type="tenancy",
        target_id=tenancy.id,
    )

    _maybe_queue(
        other_party,
        "tenancy.updated_counterparty",
        {
            "editor_name": editor_name,
            "editor_role": editor_role,
            "other_party_name": other_party_name,
            "other_party_role": other_party_role,
        },
    )

    return 2


def _refresh_user_ratings_for_user_ids(user_ids):
    Review = apps.get_model("propertylist_app", "Review")
    UserProfile = apps.get_model("propertylist_app", "UserProfile")

    now = timezone.now()

    for user_id in user_ids:
        tenant_agg = Review.objects.filter(
            role=Review.ROLE_LANDLORD_TO_TENANT,
            reviewee_id=user_id,
            active=True,
            reveal_at__isnull=False,
            reveal_at__lte=now,
            submitted_at__isnull=False,
        ).aggregate(avg=Avg("overall_rating"), cnt=Count("id"))

        landlord_agg = Review.objects.filter(
            role=Review.ROLE_TENANT_TO_LANDLORD,
            reviewee_id=user_id,
            active=True,
            reveal_at__isnull=False,
            reveal_at__lte=now,
            submitted_at__isnull=False,
        ).aggregate(avg=Avg("overall_rating"), cnt=Count("id"))

        UserProfile.objects.filter(user_id=user_id).update(
            avg_tenant_rating=float(tenant_agg["avg"] or 0.0),
            number_tenant_ratings=int(tenant_agg["cnt"] or 0),
            avg_landlord_rating=float(landlord_agg["avg"] or 0.0),
            number_landlord_ratings=int(landlord_agg["cnt"] or 0),
        )






# -------------------------------------------------------------------
# Tenancy prompts sweep (still-living + reviews)
# -------------------------------------------------------------------

@shared_task
def task_tenancy_prompts_sweep() -> int:
    Tenancy = apps.get_model("propertylist_app", "Tenancy")
    Notification = apps.get_model("propertylist_app", "Notification")
    Review = apps.get_model("propertylist_app", "Review")
    Room = apps.get_model("propertylist_app", "Room")

    now = timezone.now()
    
    UserProfile = apps.get_model("propertylist_app", "UserProfile")
    
    Message = apps.get_model("propertylist_app", "Message")

    def _tenancy_thread_links(tenancy):
        """
        Return separate mobile and web links for this tenancy conversation.
        """

        tenancy_message = (
            Message.objects
            .select_related("thread")
            .filter(metadata__tenancy_id=tenancy.id)
            .order_by("-created")
            .first()
        )

        if tenancy_message and tenancy_message.thread_id:
            # Mobile app deep link.
            deep_link = f"/app/threads/{tenancy_message.thread_id}"

            # Web/Vercel route used by email action buttons.
            cta_path = f"/messages?thread={tenancy_message.thread_id}"

            return deep_link, cta_path

        # Mobile fallback for older tenancy records with no conversation yet.
        deep_link = f"/app/tenancies/{tenancy.id}"

        # Web fallback for tenancy records with no conversation yet.
        cta_path = f"/tenancies/{tenancy.id}"

        return deep_link, cta_path
    
    
    
    def _post_tenancy_prompt_message(
        tenancy,
        *,
        event_type: str,
        body: str,
        available_action: str,
    ):
        """
        Add one system-style tenancy prompt to the existing tenancy
        conversation.

        The event key prevents Celery retries and repeated sweeps from
        creating duplicate thread messages.
        """
        tenancy_message = (
            Message.objects
            .select_related("thread")
            .filter(metadata__tenancy_id=tenancy.id)
            .order_by("-created")
            .first()
        )

        if not tenancy_message or not tenancy_message.thread_id:
            return None, None

        cycle_start = (
            tenancy.move_in_date.isoformat()
            if tenancy.move_in_date
            else "no-start"
        )

        cycle_duration = (
            tenancy.duration_months
            if tenancy.duration_months is not None
            else "no-duration"
        )

        event_key = (
            f"tenancy:{tenancy.id}:"
            f"{cycle_start}:"
            f"{cycle_duration}:"
            f"{event_type}"
        )

        existing_message = (
            Message.objects
            .select_related("thread")
            .filter(metadata__event_key=event_key)
            .first()
        )

        if existing_message:
            return existing_message.thread, existing_message

        sender = tenancy.proposed_by

        if sender is None or sender.id not in {
            tenancy.landlord_id,
            tenancy.tenant_id,
        }:
            sender = tenancy.landlord

        message = Message.objects.create(
            thread=tenancy_message.thread,
            sender=sender,
            body=body,
            message_type=Message.TYPE_TEXT,
            metadata={
                "tenancy_id": tenancy.id,
                "room_id": tenancy.room_id,
                "room_title": tenancy.room.title,
                "event_type": event_type,
                "event_key": event_key,
                "system_event": True,
                "available_actions": [available_action],
            },
        )

        return tenancy_message.thread, message
    
    
    
    
    

    def _maybe_queue_reminder(
        user,
        template_key: str,
        *,
        deep_link: str,
        cta_path: str,
        room_title: str,
        tenancy_id=None,
    ):
        profile, _ = UserProfile.objects.get_or_create(
            user=user,
        )

        if not getattr(
            profile,
            "notify_reminders",
            True,
        ):
            return

        context = {
            "user": {
                "first_name": user.first_name,
            },
            "room_title": room_title,
            "deep_link": deep_link,
            "cta_url": build_absolute_url(
                cta_path
            ),
        }

        if tenancy_id is not None:
            context["tenancy_id"] = tenancy_id

        _queue_email(
            user=user,
            template_key=template_key,
            context=context,
        )
    
    
    count = 0
    
    
        # -------------------------------------------------
    # Tenant-created tenancy claim response window
    # -------------------------------------------------
    # TEMPORARY QA RULE:
    # Give the landlord 10 minutes to Agree, Edit or select
    # "Not my tenant" after the tenant submits first.
    #
    # PRODUCTION RULE:
    # Replace the QA duration below with:
    #
    #     tenant_claim_response_window = timedelta(days=30)
    #
    # A 30-day response window is appropriate for residential
    # tenancies and prevents legitimate claims expiring too quickly.
    tenant_claim_response_window = timedelta(minutes=10)

    tenant_claim_expiry_cutoff = (
        now - tenant_claim_response_window
    )

    expired_tenant_claims = (
        Tenancy.objects
        .select_related(
            "room",
            "landlord",
            "tenant",
            "proposed_by",
        )
        .filter(
            status=Tenancy.STATUS_PROPOSED,
            proposed_by_id=F("tenant_id"),
            landlord_confirmed_at__isnull=True,
            created_at__lte=tenant_claim_expiry_cutoff,
        )
    )

    for tenancy in expired_tenant_claims:
        tenancy.status = Tenancy.STATUS_CANCELLED
        tenancy.review_open_at = None
        tenancy.review_deadline_at = None
        tenancy.still_living_check_at = None
        tenancy.still_living_confirmed_at = None
        tenancy.save(
            update_fields=[
                "status",
                "review_open_at",
                "review_deadline_at",
                "still_living_check_at",
                "still_living_confirmed_at",
                "updated_at",
            ]
        )

        # The tenant-created claim never took the listing offline,
        # so the room availability must remain unchanged.
        task_send_tenancy_notification.delay(
            tenancy.id,
            "expired_unverified",
        )

        count += 1
    
    
    
        # -------------------------------------------------
    # 1) tenancy ending reminder
    # -------------------------------------------------
    due_checks = (
        Tenancy.objects
        .select_related("room", "landlord", "tenant")
        .filter(
            status__in=[
                Tenancy.STATUS_CONFIRMED,
                Tenancy.STATUS_ACTIVE,
            ],
            still_living_check_at__isnull=False,
            still_living_check_at__lte=now,
            still_living_confirmed_at__isnull=True,
        )
    )

    for tenancy in due_checks:
        landlord_done = bool(
            getattr(
                tenancy,
                "still_living_landlord_confirmed_at",
                None,
            )
        )
        tenant_done = bool(
            getattr(
                tenancy,
                "still_living_tenant_confirmed_at",
                None,
            )
        )

        # Both parties have completed the check.
        if landlord_done and tenant_done:
            tenancy.still_living_confirmed_at = now
            tenancy.save(
                update_fields=["still_living_confirmed_at"]
            )
            continue

        # Separate mobile and web destinations.
        deep_link, cta_path = _tenancy_thread_links(tenancy)

        title = "Your tenancy is ending soon"
        body = (
            f"Your tenancy for {tenancy.room.title} is due to end soon. "
            "Update the tenancy information if you are continuing. "
            "If you are moving out, no action is required."
        )
        
        prompt_thread, prompt_message = _post_tenancy_prompt_message(
            tenancy,
            event_type="still_living_check",
            body=(
                "Your tenancy is ending soon.\n\n"
                "If the tenancy is continuing, update the tenancy "
                "information. If you are moving out, no action is required."
            ),
            available_action="update_tenancy",
        )

        if prompt_thread is not None:
            # Mobile app deep link.
            deep_link = f"/app/threads/{prompt_thread.id}"

            # Web/Vercel route used by email action buttons.
            cta_path = f"/messages?thread={prompt_thread.id}"
                
        

        def _notify_user(user, template_key):
            latest_accepted_extension = (
                tenancy.extensions
                .filter(
                    status="accepted",
                    responded_at__isnull=False,
                )
                .order_by(
                    "-responded_at",
                    "-id",
                )
                .first()
            )

            if latest_accepted_extension:
                cycle_started_at = (
                    latest_accepted_extension.responded_at
                )
            else:
                confirmation_times = [
                    value
                    for value in [
                        tenancy.landlord_confirmed_at,
                        tenancy.tenant_confirmed_at,
                    ]
                    if value is not None
                ]

                cycle_started_at = (
                    max(confirmation_times)
                    if confirmation_times
                    else tenancy.created_at
                )

            # Both parties should open the tenancy itself.
            target_type = "still_living_check"
            target_id = tenancy.id

            audience = (
                Notification.Audience.LANDLORD
                if user.id == tenancy.landlord_id
                else Notification.Audience.SEEKER
            )


            reminder_target = Q(
                target_type="still_living_check",
                target_id=tenancy.id,
            )

            if user.id == tenancy.landlord_id:
                legacy_booking_ids = Booking.objects.filter(
                    room=tenancy.room,
                    user=tenancy.tenant,
                    is_deleted=False,
                ).values_list("id", flat=True)

                reminder_target |= Q(
                    target_type="booking",
                    target_id__in=legacy_booking_ids,
                )

            reminder_exists = (
                Notification.objects
                .filter(
                    user=user,
                    type="tenancy_still_living_check",
                    created_at__gte=cycle_started_at,
                )
                .filter(reminder_target)
                .exists()
            )

            if reminder_exists:
                return 0

            notification = Notification.objects.create(
                user=user,
                type="tenancy_still_living_check",
                target_type=target_type,
                target_id=target_id,
                thread=prompt_thread,
                message=prompt_message,
                title=title,
                body=body,
                audience=audience,
            )

            # Realtime Envelope / Inbox update.
            if prompt_thread and prompt_message:
                push_user_realtime_event(
                    user.id,
                    "new_message",
                    {
                        "message_id": prompt_message.id,
                        "thread_id": prompt_thread.id,
                        "sender_id": prompt_message.sender_id,
                    },
                )

                # Realtime Bell update.
                push_user_realtime_event(
                    user.id,
                    "new_notification",
                    {
                        "kind": "tenancy_still_living_check",
                        "notification_id": notification.id,
                        "message_id": prompt_message.id,
                        "thread_id": prompt_thread.id,
                    },
                )

            _maybe_queue_reminder(
                user,
                template_key,
                deep_link=deep_link,
                cta_path=cta_path,
                room_title=tenancy.room.title,
                tenancy_id=tenancy.id,
            )

            return 1

        landlord_notification_created = 0
        tenant_notification_created = 0

        if not landlord_done:
            landlord_notification_created = _notify_user(
                tenancy.landlord,
                "tenancy.still_living_check_landlord",
            )
            count += landlord_notification_created

        if not tenant_done:
            tenant_notification_created = _notify_user(
                tenancy.tenant,
                "tenancy.still_living_check",
            )
            count += tenant_notification_created

        # TEMPORARY QA RULE:
        # When neither party has updated the tenancy information,
        # open the review window 10 minutes after the ending reminder
        # is first created. Production must revert to end date + 7 days.
        reminder_created = bool(
            landlord_notification_created
            or tenant_notification_created
        )

        if (
            not landlord_done
            and not tenant_done
            and reminder_created
        ):
            # TEMPORARY QA RULE:
            # QA: Open reviews 10 minutes after the ending reminder,
            # then keep the private/double-blind review window open for 10 minutes.
            #
            # PRODUCTION RULE:
            # review_deadline_at must be:
            #
            #     tenancy.review_open_at + timedelta(days=30)
            #
            tenancy.review_open_at = (
                now + timedelta(minutes=10)
            )

            tenancy.review_deadline_at = (
                tenancy.review_open_at
                + timedelta(minutes=10)
            )
            tenancy.save(
                update_fields=[
                    "review_open_at",
                    "review_deadline_at",
                ]
            )
            
    
    
    # ---------------------------------------------------------
    # QA: CLOSE TENANCY UPDATE WINDOW
    # ---------------------------------------------------------
    # Once review_open_at is reached:
    #
    # 1. unresolved renewal proposals expire
    # 2. renewal Accept/Reject actions disappear
    # 3. Update tenancy actions disappear
    # 4. tenancy becomes ended
    # 5. the review phase can begin
    #
    # The API also independently rejects stale renewal actions,
    # so keeping an old browser tab open cannot bypass this rule.
    tenancies_reaching_review = (
        Tenancy.objects
        .filter(
            status__in=[
                Tenancy.STATUS_CONFIRMED,
                Tenancy.STATUS_ACTIVE,
            ],
            review_open_at__isnull=False,
            review_open_at__lte=now,
            still_living_confirmed_at__isnull=True,
        )
    )

    for tenancy in tenancies_reaching_review:
        # -----------------------------------------------------
        # Expire any unresolved renewal proposal.
        # -----------------------------------------------------
        open_extensions = tenancy.extensions.filter(
            status="proposed",
        )

        extension_ids = list(
            open_extensions.values_list(
                "id",
                flat=True,
            )
        )

        if extension_ids:
            open_extensions.update(
                status="canceled",
            )

            # Remove Accept / Reject from the proposal messages.
            extension_messages = Message.objects.filter(
                metadata__extension_id__in=extension_ids,
                metadata__event_type="tenancy_extension_proposed",
                metadata__system_event=True,
            )

            for message in extension_messages:
                metadata = dict(
                    message.metadata or {}
                )
                metadata["available_actions"] = []

                message.metadata = metadata
                message.save(
                    update_fields=["metadata"]
                )

        # -----------------------------------------------------
        # Remove Update tenancy from the ending-soon message.
        # -----------------------------------------------------
        ending_messages = Message.objects.filter(
            metadata__tenancy_id=tenancy.id,
            metadata__event_type="still_living_check",
            metadata__system_event=True,
        )

        for message in ending_messages:
            metadata = dict(
                message.metadata or {}
            )
            metadata["available_actions"] = []

            message.metadata = metadata
            message.save(
                update_fields=["metadata"]
            )

        # -----------------------------------------------------
        # Tenancy is now closed to all further mutations.
        # -----------------------------------------------------
        tenancy.status = Tenancy.STATUS_ENDED
        tenancy.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        ) 
        
     
            
            
    # -------------------------------------------------
    # 2) reviews open -> notifications (if any side missing)
    # -------------------------------------------------
    
    due_reviews = Tenancy.objects.filter(
        status=Tenancy.STATUS_ENDED,
        review_open_at__isnull=False,
        review_open_at__lte=now,
    )
    
    for t in due_reviews:
        tenant_done = Review.objects.filter(
            tenancy=t,
            role=Review.ROLE_TENANT_TO_LANDLORD,
        ).exists()

        landlord_done = Review.objects.filter(
            tenancy=t,
            role=Review.ROLE_LANDLORD_TO_TENANT,
        ).exists()

        # Both parties have already reviewed.
        if tenant_done and landlord_done:
            continue

        # Add one review-available message to the existing tenancy thread.
        # Repeated Celery runs reuse the same message.
        prompt_thread, prompt_message = _post_tenancy_prompt_message(
            t,
            event_type="review_available",
            body=(
                "Your review window is now open.\n\n"
                "You can now leave a review for this tenancy."
            ),
            available_action="leave_review",
        )

        # Mobile app deep link.
        review_deep_link = f"/app/tenancies/{t.id}/reviews"

        # Notify the landlord only if the landlord has not reviewed.
        if not landlord_done:
            notification, notification_created = (
                Notification.objects.get_or_create(
                    user=t.landlord,
                    type="review_available",
                    target_type="tenancy_review",
                    target_id=t.id,
                    defaults={
                        "thread": prompt_thread,
                        "message": prompt_message,
                        "audience": Notification.Audience.LANDLORD,
                        "title": "Review available",
                        "body": (
                            f"You can now leave a review for "
                            f"{t.room.title}."
                        ),
                    },
                )
            )

            if notification_created:
                if prompt_thread and prompt_message:
                    push_user_realtime_event(
                        t.landlord.id,
                        "new_message",
                        {
                            "message_id": prompt_message.id,
                            "thread_id": prompt_thread.id,
                            "sender_id": prompt_message.sender_id,
                        },
                    )

                    push_user_realtime_event(
                        t.landlord.id,
                        "new_notification",
                        {
                            "kind": "review_available",
                            "notification_id": notification.id,
                            "message_id": prompt_message.id,
                            "thread_id": prompt_thread.id,
                        },
                    )

                _maybe_queue_reminder(
                    t.landlord,
                    "tenancy.review_available",
                    deep_link=review_deep_link,
                    cta_path=f"/leave-a-review?tenancy={t.id}",
                    room_title=t.room.title,
                    tenancy_id=t.id,
                )

                count += 1

        # Notify the tenant only if the tenant has not reviewed.
        
        if not tenant_done:
            notification, notification_created = (
                Notification.objects.get_or_create(
                    user=t.tenant,
                    type="review_available",
                    target_type="tenancy_review",
                    target_id=t.id,
                    defaults={
                        "thread": prompt_thread,
                        "message": prompt_message,
                        "audience": Notification.Audience.SEEKER,
                        "title": "Review available",
                        "body": (
                            f"You can now leave a review for "
                            f"{t.room.title}."
                        ),
                    },
                )
            )

            if notification_created:
                if prompt_thread and prompt_message:
                    push_user_realtime_event(
                        t.tenant.id,
                        "new_message",
                        {
                            "message_id": prompt_message.id,
                            "thread_id": prompt_thread.id,
                            "sender_id": prompt_message.sender_id,
                        },
                    )

                    push_user_realtime_event(
                        t.tenant.id,
                        "new_notification",
                        {
                            "kind": "review_available",
                            "notification_id": notification.id,
                            "message_id": prompt_message.id,
                            "thread_id": prompt_thread.id,
                        },
                    )

                _maybe_queue_reminder(
                    t.tenant,
                    "tenancy.review_available",
                    deep_link=review_deep_link,
                    cta_path=f"/leave-a-review?tenancy={t.id}",
                    room_title=t.room.title,
                    tenancy_id=t.id,
                )

                count += 1
    # -------------------------------------------------
    # 3) REVEAL + RATING UPDATE (your schema)
    #
    # Review is visible when:
    # - active == True
    # - reveal_at <= now
    #
    # Rating should be calculated from ONLY revealed reviews (active=True).
    # -------------------------------------------------

    # 3a) Reveal any reviews whose reveal time has passed
    to_reveal = list(
    Review.objects
    .filter(
        active=False,
        reveal_at__isnull=False,
        reveal_at__lte=now,
    )
    .select_related(
        "reviewee",
        "tenancy",
        "tenancy__room",
    )
    )

    revealed_count = 0

    for review in to_reveal:
        review.active = True
        review.save(update_fields=["active"])

        revealed_count += 1

        tenancy = review.tenancy
        reviewee = review.reviewee

        if not reviewee:
            continue
        
        
        if reviewee.id == tenancy.landlord_id:
            reviewee_audience = Notification.Audience.LANDLORD
        elif reviewee.id == tenancy.tenant_id:
            reviewee_audience = Notification.Audience.SEEKER
        else:
            reviewee_audience = Notification.Audience.BOTH

        # -------------------------------------------------
        # Review revealed:
        # 1) shared RentCrib inbox/envelope message
        # 2) bell notification for the reviewee
        # 3) email for the reviewee
        # 4) realtime envelope update
        # 5) realtime bell update
        # -------------------------------------------------

        prompt_thread, prompt_message = _post_tenancy_prompt_message(
            tenancy,
            event_type="review_revealed",
            body=(
                "A review from this tenancy is now available.\n\n"
                "Open your reviews to view it."
            ),
            available_action="view_review",
        )

        notification, notification_created = (
            Notification.objects.get_or_create(
                user=reviewee,
                type="review_revealed",
                target_type="tenancy_review",
                target_id=review.id,
                defaults={
                    "thread": prompt_thread,
                    "message": prompt_message,
                    "title": "Review now available",
                    "audience": reviewee_audience,
                    "body": (
                        f"A review from your tenancy at "
                        f"{tenancy.room.title} is now available to view."
                    ),
                },
            )
        )

        if notification_created:
            if prompt_thread and prompt_message:
                # Realtime Envelope / Inbox update.
                push_user_realtime_event(
                    reviewee.id,
                    "new_message",
                    {
                        "message_id": prompt_message.id,
                        "thread_id": prompt_thread.id,
                        "sender_id": prompt_message.sender_id,
                    },
                )

                # Realtime Bell update.
                push_user_realtime_event(
                    reviewee.id,
                    "new_notification",
                    {
                        "kind": "review_revealed",
                        "notification_id": notification.id,
                        "message_id": prompt_message.id,
                        "thread_id": prompt_thread.id,
                    },
                )

            _maybe_queue_reminder(
                reviewee,
                "tenancy.review_revealed",

                # Mobile app deep link.
                deep_link=f"/app/tenancies/{tenancy.id}/reviews",

                # Web/Vercel route used by email button.
                cta_path=(
                    f"/reviews/{review.id}?role="
                    f"{'landlord' if reviewee_audience == Notification.Audience.LANDLORD else 'seeker'}"
                ),

                room_title=tenancy.room.title,
                tenancy_id=tenancy.id,
            )

            count += 1
            
    if revealed_count:
        # refresh tenant ratings for tenants affected by newly revealed landlord->tenant reviews
        affected_tenant_ids = (
            Review.objects.filter(
                active=True,
                reveal_at__isnull=False,
                reveal_at__lte=now,
                role=Review.ROLE_LANDLORD_TO_TENANT,
            )
            .values_list("reviewee_id", flat=True)
            .distinct()
        )

        affected_user_ids = (
            Review.objects.filter(
                active=True,
                reveal_at__isnull=False,
                reveal_at__lte=now,
            )
            .values_list("reviewee_id", flat=True)
            .distinct()
        )

        _refresh_user_ratings_for_user_ids(affected_user_ids)



    # 3b) Recalculate ratings for rooms affected by reveal
    if revealed_count:
        # rooms impacted by newly revealed reviews
        room_ids = (
            Review.objects.filter(active=True, reveal_at__lte=now)
            .exclude(tenancy__room_id__isnull=True)
            .values_list("tenancy__room_id", flat=True)
            .distinct()
        )

        for room_id in room_ids:
            agg = Review.objects.filter(
                tenancy__room_id=room_id,
                role=Review.ROLE_TENANT_TO_LANDLORD,  # only tenant -> landlord affects room rating
                active=True,
                reveal_at__isnull=False,
                reveal_at__lte=now,
            ).aggregate(
                avg=Avg("overall_rating"),
                cnt=Count("id"),
            )

            avg_val = float(agg["avg"] or 0.0)
            cnt_val = int(agg["cnt"] or 0)

            Room.objects.filter(id=room_id).update(
                avg_rating=avg_val,
                number_rating=cnt_val,
            )

    return count

# -------------------------------------------------------------------
# Tenancy lifecycle + automatic review window
# -------------------------------------------------------------------


@shared_task
def task_refresh_tenancy_status_and_review_windows():
    Tenancy = apps.get_model("propertylist_app", "Tenancy")

    today = timezone.localdate()

    for t in (
        Tenancy.objects
        .select_related("room")
        .exclude(status=Tenancy.STATUS_CANCELLED)
        .iterator()
    ):
        if (
            t.status == Tenancy.STATUS_CONFIRMED
            and t.move_in_date <= today
        ):
            t.status = Tenancy.STATUS_ACTIVE

        end_date = compute_end_date(
            t.move_in_date,
            t.duration_months,
        )

        if (
            t.status in (
                Tenancy.STATUS_CONFIRMED,
                Tenancy.STATUS_ACTIVE,
            )
            and end_date < today
        ):
            t.status = Tenancy.STATUS_ENDED

            # The tenancy has genuinely ended.
            # Make the room available immediately for reletting.
            room = t.room

            if not room.is_available:
                room.is_available = True
                room.save(
                    update_fields=[
                        "is_available",
                        "updated_at",
                    ]
                )

        if (
            t.review_open_at is None
            or t.review_deadline_at is None
            or t.still_living_check_at is None
        ):
            ro, rd, sl = compute_review_window(
                t.move_in_date,
                t.duration_months,
            )

            t.review_open_at = t.review_open_at or ro
            t.review_deadline_at = t.review_deadline_at or rd
            t.still_living_check_at = (
                t.still_living_check_at or sl
            )

        t.save()