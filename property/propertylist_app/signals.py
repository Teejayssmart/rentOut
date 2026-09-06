from django.apps import apps
from django.db.models import Avg, Count, Exists, OuterRef, Q
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from propertylist_app.services.message_threads import (
    get_or_create_canonical_thread,
)


from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import (
    Booking,
    Message,
    MessageThread,
    MessageThreadState,
    Notification,
    Review,
    Room,
    UserProfile,
)
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.realtime import push_user_realtime_event
from propertylist_app.services.reviews import (
    update_room_rating_from_revealed_reviews,
)


def _recalc_room_rating(room: Room) -> None:
    """
    Recalculate a room's rating using only active, revealed
    tenant-to-landlord tenancy reviews.
    """
    now = timezone.now()

    aggregate = Review.objects.filter(
        tenancy__room=room,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        active=True,
        reveal_at__isnull=False,
        reveal_at__lte=now,
    ).aggregate(
        avg=Avg("overall_rating"),
        count=Count("id"),
    )

    room.avg_rating = float(aggregate["avg"] or 0.0)
    room.number_rating = int(aggregate["count"] or 0)

    room.save(
        update_fields=[
            "avg_rating",
            "number_rating",
        ]
    )


@receiver(post_save, sender=Review)
def review_saved_update_room_rating(
    sender,
    instance: Review,
    created,
    **kwargs,
) -> None:
    tenancy = getattr(instance, "tenancy", None)
    room = getattr(tenancy, "room", None)

    if not room:
        return

    update_room_rating_from_revealed_reviews(room)


@receiver(post_delete, sender=Review)
def review_deleted_update_room_rating(
    sender,
    instance: Review,
    **kwargs,
) -> None:
    tenancy = getattr(instance, "tenancy", None)
    room = getattr(tenancy, "room", None)

    if not room:
        return

    update_room_rating_from_revealed_reviews(room)


def _queue_email(
    *,
    user,
    template_key: str,
    context: dict | None = None,
) -> None:
    """
    Queue an email through the notifications pipeline.

    The email is queued only when an active email template exists for
    the supplied template key. It is not sent immediately.
    """
    if not user:
        return

    template_exists = NotificationTemplate.objects.filter(
        key=template_key,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        is_active=True,
    ).exists()

    if not template_exists:
        return

    OutboundNotification.objects.create(
        user=user,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key=template_key,
        context=context or {},
    )


@receiver(post_save, sender=Booking)
def booking_created_queue_emails(
    sender,
    instance: Booking,
    created,
    **kwargs,
) -> None:
    if not created:
        return
    

    room = instance.room
    owner = getattr(room, "property_owner", None)
    booker = instance.user
    
    # ---------------------------------------------------------
    # Shared RentCrib inbox/envelope event for the new viewing.
    # ---------------------------------------------------------
    thread = None
    system_message = None

    if owner and booker:
        thread = get_or_create_canonical_thread(
            landlord=owner,
            seeker=booker,
            room=room,
        )

        event_key = f"booking:{instance.id}:created"

        system_message = (
            Message.objects
            .filter(
                metadata__event_key=event_key,
            )
            .first()
        )

        if system_message is None:
            system_message = Message.objects.create(
                thread=thread,
                sender=booker,
                body=(
                    "Viewing booked\n\n"
                    f"A viewing has been booked for {room.title}.\n\n"
                    f"Viewing time: "
                    f"{timezone.localtime(instance.start).strftime('%d %b %Y, %H:%M')}"
                ),
                message_type=Message.TYPE_TEXT,
                metadata={
                    "system_event": True,
                    "event_type": "booking_created",
                    "event_key": event_key,
                    "booking_id": instance.id,
                    "room_id": room.id,
                    "room_title": room.title,
                    "start": instance.start.isoformat(),
                    "end": (
                        instance.end.isoformat()
                        if instance.end
                        else None
                    ),
                },
            )

            # Both parties' envelope/inbox should update immediately.
            for user in (owner, booker):
                push_user_realtime_event(
                    user.id,
                    "new_message",
                    {
                        "message_id": system_message.id,
                        "thread_id": thread.id,
                        "sender_id": system_message.sender_id,
                    },
                )

        # Landlord bell notification.
        owner_profile, _ = UserProfile.objects.get_or_create(
            user=owner,
        )

        if getattr(
            owner_profile,
            "notify_confirmations",
            True,
        ):
            owner_notification, owner_notification_created = (
                Notification.objects.get_or_create(
                    user=owner,
                    type="booking_created",
                    target_type="message",
                    target_id=system_message.id,
                    defaults={
                        "thread": thread,
                        "message": system_message,
                        "audience": Notification.Audience.LANDLORD,
                        "title": "New viewing booked",
                        "body": (
                            f"A viewing has been booked for "
                            f"{room.title}."
                        ),
                    },
                )
            )

            if owner_notification_created:
                push_user_realtime_event(
                    owner.id,
                    "new_notification",
                    {
                        "kind": "booking_created",
                        "notification_id": owner_notification.id,
                        "message_id": system_message.id,
                        "thread_id": thread.id,
                    },
                )
    

    # Mobile app deep link.
    booking_deep_link = f"/app/bookings/{instance.id}"

    # Web/Vercel route used by email action buttons.
    booking_full_url = build_absolute_url(
        f"/viewings/{instance.id}",
        force_login=True,
    )

    if owner:
        booker_name = (
            booker.get_full_name().strip()
            or booker.username
            or booker.first_name
            or "A prospective tenant"
        )

        _queue_email(
            user=owner,
            template_key="booking.new",
            context={
                "user": {
                    "first_name": owner.first_name,
                },
                "booker": {
                    "name": booker_name,
                },
                "room": {
                    "title": room.title,
                },
                "booking_id": instance.id,
                "room_id": room.id,
                "deep_link": booking_deep_link,
                "cta_url": booking_full_url,
            },
        )

    if booker:
        owner_name = ""

        if owner:
            owner_name = (
                owner.get_full_name()
                or owner.username
                or owner.first_name
                or ""
            )

        _queue_email(
            user=booker,
            template_key="booking.confirmation",
            context={
                "user": {
                    "first_name": booker.first_name,
                },
                "room": {
                    "title": room.title,
                    "owner_name": owner_name,
                },
                "booking_id": instance.id,
                "room_id": room.id,
                "deep_link": booking_deep_link,
                "cta_url": booking_full_url,
            },
        )


@receiver(post_save, sender=Message)
def message_created_create_notifications(
    sender,
    instance: Message,
    created,
    **kwargs,
) -> None:
    if not created:
        return

    if instance.message_type != Message.TYPE_TEXT:
        return

    metadata = instance.metadata or {}

    if metadata.get("system_event") is True:
        return

    thread: MessageThread = instance.thread

    recipients = thread.participants.exclude(
        pk=instance.sender_id
    ).all()

    MessageThreadState.objects.filter(
        user__in=recipients,
        thread=thread,
        in_bin=True,
    ).update(
        in_bin=False,
    )
    # ---------------------------------------------------------
    # ORDINARY HUMAN CHAT MESSAGE
    # ---------------------------------------------------------

    notifications_to_create = []
    notification_users = []

    # Mobile app deep link.
    deep_link = f"/app/threads/{thread.id}"

    # Web/Vercel route used by email action buttons.
    full_url = build_absolute_url(
        f"/messages?thread={thread.id}",
        force_login=False,
    )

    sender_name = (
        instance.sender.get_full_name()
        or instance.sender.get_username()
    )

    message_snippet = instance.body[:200] if instance.body else ""

    for user in recipients:
        profile, _ = UserProfile.objects.get_or_create(
            user=user
        )

        thread_audience = (
            Notification.Audience.LANDLORD
            if thread.landlord_id == user.id
            else (
                Notification.Audience.SEEKER
                if thread.seeker_id == user.id
                else Notification.Audience.BOTH
            )
        )

        realtime_visible = (
            thread_audience == Notification.Audience.BOTH
            or profile.role == thread_audience
        )

        if realtime_visible:
            # Realtime chat delivery is core messaging behaviour.
            # It must not depend on bell/email notification preferences.
            push_user_realtime_event(
                user.id,
                "new_message",
                {
                    "message_id": instance.id,
                    "thread_id": thread.id,
                    "sender_id": instance.sender_id,
                },
            )
            
            
            deleted_at = (
                MessageThreadState.objects
                .filter(
                    user=user,
                    thread=thread,
                )
                .values_list("deleted_at", flat=True)
                .first()
            )

            visible_thread_messages = Message.objects.filter(
                thread=thread
            )

            if deleted_at is not None:
                visible_thread_messages = visible_thread_messages.filter(
                    created__gt=deleted_at
                )

            thread_unread_count = (
                visible_thread_messages
                .filter(
                    Q(metadata__system_event=True)
                    | ~Q(sender=user)
                )
                .exclude(reads__user=user)
                .distinct()
                .count()
            )

            if profile.role == "landlord":
                base_threads = MessageThread.objects.filter(
                    participants=user,
                ).filter(
                    Q(landlord=user)
                    | Q(
                        landlord__isnull=True,
                        seeker__isnull=True,
                    )
                )
            else:
                base_threads = MessageThread.objects.filter(
                    participants=user,
                ).filter(
                    Q(seeker=user)
                    | Q(
                        landlord__isnull=True,
                        seeker__isnull=True,
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
                base_threads = base_threads.exclude(
                    id__in=bin_thread_ids,
                )
                
            
            hidden_by_delete = MessageThreadState.objects.filter(
                user=user,
                thread_id=OuterRef("thread_id"),
                deleted_at__isnull=False,
                deleted_at__gte=OuterRef("created"),
            )
            
                

            account_unread_total = (
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

            push_user_realtime_event(
                user.id,
                "unread_count_changed",
                {
                    "thread_id": thread.id,
                    "thread_unread_count": thread_unread_count,
                    "account_unread_total": account_unread_total,
                },
            )

        if not getattr(profile, "notify_messages", True):
            continue

        if not getattr(profile, "notify_messages", True):
            continue

        notification_users.append(user)



        notification_audience = thread_audience

        notifications_to_create.append(
            Notification(
                user=user,
                type=Notification.Type.MESSAGE,
                thread=thread,
                message=instance,
                title="New message",
                body=message_snippet,
                audience=notification_audience,
            )
        )

    if notifications_to_create:
        Notification.objects.bulk_create(
            notifications_to_create,
            ignore_conflicts=True,
        )




    # Notify the frontend only after the notification rows exist.
    for user in notification_users:
        profile, _ = UserProfile.objects.get_or_create(
            user=user
        )

        notification_audience = (
            Notification.Audience.LANDLORD
            if thread.landlord_id == user.id
            else (
                Notification.Audience.SEEKER
                if thread.seeker_id == user.id
                else Notification.Audience.BOTH
            )
        )

        realtime_visible = (
            notification_audience == Notification.Audience.BOTH
            or profile.role == notification_audience
        )

        if realtime_visible:
            push_user_realtime_event(
                user.id,
                "new_notification",
                {
                    "kind": "message",
                    "message_id": instance.id,
                    "thread_id": thread.id,
                },
            )

        _queue_email(
            user=user,
            template_key="message.new",
            context={
                "user": {
                    "first_name": user.first_name,
                },
                "sender": {
                    "name": sender_name,
                },
                "thread_id": thread.id,
                "message_id": instance.id,
                "deep_link": deep_link,
                "cta_url": full_url,

                # Backwards-compatible variables for older templates.
                "thread_url": full_url,
                "snippet": message_snippet,
            },
        )
# -------------------------------------------------------------------
# TenancyExtension notifications
# -------------------------------------------------------------------


def _ext_other_party(extension):
    """
    Return the party who should be notified about a new proposal.

    Landlord proposal: notify the tenant.
    Tenant proposal: notify the landlord.
    """
    tenancy = extension.tenancy

    if extension.proposed_by_id == getattr(
        tenancy,
        "landlord_id",
        None,
    ):
        return tenancy.tenant

    return tenancy.landlord


@receiver(
    pre_save,
    sender=apps.get_model(
        "propertylist_app",
        "TenancyExtension",
    ),
)
def tenancy_extension_cache_old_status(
    sender,
    instance,
    **kwargs,
) -> None:
    if not instance.pk:
        instance._old_status = None
        return

    instance._old_status = sender.objects.filter(
        pk=instance.pk
    ).values_list(
        "status",
        flat=True,
    ).first()


@receiver(
    post_save,
    sender=apps.get_model(
        "propertylist_app",
        "TenancyExtension",
    ),
)
def tenancy_extension_notifications(
    sender,
    instance,
    created,
    **kwargs,
) -> None:
    if not getattr(instance, "tenancy_id", None):
        return

    tenancy = instance.tenancy

    # Mobile app destination.
    deep_link = f"/app/tenancies/{tenancy.id}"

    # Web/Vercel destination.
    cta_url = build_absolute_url(
        f"/tenancies/{tenancy.id}",
    )


    def create_extension_system_message(
        event_type: str,
        body: str,
        *,
        available_actions=None,
        responder_user_id=None,
    ):
        landlord = tenancy.landlord
        tenant = tenancy.tenant

        if not landlord or not tenant:
            return None, None

        thread = get_or_create_canonical_thread(
            landlord=landlord,
            seeker=tenant,
            room=tenancy.room,
        )

        event_key = (
            f"tenancy_extension:{instance.id}:"
            f"{event_type}"
        )

        message = (
            Message.objects
            .filter(
                metadata__event_key=event_key,
            )
            .first()
        )

        if message is None:
            message_sender = (
                instance.proposed_by
                or landlord
            )

            metadata = {
                "system_event": True,
                "event_type": event_type,
                "event_key": event_key,
                "tenancy_id": tenancy.id,
                "extension_id": instance.id,
                "room_id": tenancy.room_id,
                "room_title": tenancy.room.title,
            }

            if available_actions:
                metadata["available_actions"] = list(
                    available_actions
                )

            if responder_user_id is not None:
                metadata["responder_user_id"] = (
                    responder_user_id
                )

            message = Message.objects.create(
                thread=thread,
                sender=message_sender,
                body=body,
                message_type=Message.TYPE_TEXT,
                metadata=metadata,
            )

            # Shared RentCrib envelope event for both parties.
            for user in (
                landlord,
                tenant,
            ):
                push_user_realtime_event(
                    user.id,
                    "new_message",
                    {
                        "message_id": message.id,
                        "thread_id": thread.id,
                        "sender_id": message.sender_id,
                    },
                )

        return thread, message








    def maybe_queue_email(user, template_key: str) -> None:
        if not user:
            return

        profile, _ = UserProfile.objects.get_or_create(
            user=user,
        )

        if not getattr(
            profile,
            "notify_confirmations",
            True,
        ):
            return

        proposed_by = getattr(
            instance,
            "proposed_by",
            None,
        )

        proposer_name = ""

        if proposed_by:
            proposer_name = (
                proposed_by.get_full_name()
                or proposed_by.username
                or proposed_by.first_name
                or ""
            )

        proposed_start_date = getattr(
            instance,
            "proposed_start_date",
            None,
        )

        proposed_start_date_value = (
            proposed_start_date.isoformat()
            if proposed_start_date
            else ""
        )

        _queue_email(
            user=user,
            template_key=template_key,
            context={
                "user": {
                    "first_name": user.first_name,
                },
                "tenancy_id": tenancy.id,
                "extension_id": instance.id,
                "room_title": tenancy.room.title,
                "proposer_name": proposer_name,
                "proposed_start_date": (
                    proposed_start_date_value
                ),
                "proposed_duration_months": (
                    instance.proposed_duration_months
                ),
                "deep_link": deep_link,
                "cta_url": cta_url,
            },
        )

    proposed_start_date = getattr(
        instance,
        "proposed_start_date",
        None,
    )

    if proposed_start_date:
        proposed_start_date_text = (
            proposed_start_date.strftime("%d %B %Y")
        )
    else:
        proposed_start_date_text = (
            "the agreed renewal date"
        )

    proposed_duration_months = getattr(
        instance,
        "proposed_duration_months",
        None,
    )

    duration_text = (
        f"{proposed_duration_months} "
        f"month{'s' if proposed_duration_months != 1 else ''}"
        if proposed_duration_months
        else "the agreed duration"
    )

    proposed_start_date = getattr(
        instance,
        "proposed_start_date",
        None,
    )

    proposed_start_date_text = (
        proposed_start_date.strftime("%d %B %Y")
        if proposed_start_date
        else "the agreed renewal date"
    )

    proposed_duration_months = getattr(
        instance,
        "proposed_duration_months",
        None,
    )

    duration_text = (
        f"{proposed_duration_months} "
        f"month{'s' if proposed_duration_months != 1 else ''}"
        if proposed_duration_months
        else "the agreed duration"
    )

    if created:
        other_party = _ext_other_party(instance)
        proposer = instance.proposed_by

        if not other_party or not proposer:
            return

        responder_audience = (
            Notification.Audience.LANDLORD
            if other_party.id == tenancy.landlord_id
            else (
                Notification.Audience.SEEKER
                if other_party.id == tenancy.tenant_id
                else Notification.Audience.BOTH
            )
        )

        proposer_audience = (
            Notification.Audience.LANDLORD
            if proposer.id == tenancy.landlord_id
            else (
                Notification.Audience.SEEKER
                if proposer.id == tenancy.tenant_id
                else Notification.Audience.BOTH
            )
        )

        thread, message = create_extension_system_message(
            "tenancy_extension_proposed",
            (
                "Tenancy renewal proposed\n\n"
                f"A renewal has been proposed for "
                f"{tenancy.room.title}, starting "
                f"{proposed_start_date_text} for "
                f"{duration_text}.\n\n"
                "Review the renewal information and respond."
            ),
            available_actions=[
                "accept",
                "reject",
            ],
            responder_user_id=other_party.id,
        )

        # ---------------------------------------------------------
        # RESPONDER BELL
        # ---------------------------------------------------------
        responder_notification, responder_created = (
            Notification.objects.get_or_create(
                user=other_party,
                type="tenancy_extension_proposed",
                target_type="tenancy_extension",
                target_id=instance.id,
                defaults={
                    "thread": thread,
                    "message": message,
                    "audience": responder_audience,
                    "title": "Tenancy renewal proposed",
                    "body": (
                        f"A renewal has been proposed for "
                        f"{tenancy.room.title}, starting "
                        f"{proposed_start_date_text} for "
                        f"{duration_text}. Review the renewal "
                        "information and respond."
                    ),
                },
            )
        )

        if responder_created and thread and message:
            push_user_realtime_event(
                other_party.id,
                "new_notification",
                {
                    "kind": "tenancy_extension_proposed",
                    "notification_id": (
                        responder_notification.id
                    ),
                    "message_id": message.id,
                    "thread_id": thread.id,
                    "extension_id": instance.id,
                },
            )

        # ---------------------------------------------------------
        # PROPOSER CONFIRMATION BELL
        # ---------------------------------------------------------
        proposer_notification, proposer_created = (
            Notification.objects.get_or_create(
                user=proposer,
                type="tenancy_extension_proposed",
                target_type="tenancy_extension",
                target_id=instance.id,
                defaults={
                    "thread": thread,
                    "message": message,
                    "audience": proposer_audience,
                    "title": "Tenancy renewal proposed",
                    "body": (
                        f"Your renewal proposal for "
                        f"{tenancy.room.title}, starting "
                        f"{proposed_start_date_text} for "
                        f"{duration_text}, has been sent."
                    ),
                },
            )
        )

        if proposer_created and thread and message:
            push_user_realtime_event(
                proposer.id,
                "new_notification",
                {
                    "kind": "tenancy_extension_proposed",
                    "notification_id": (
                        proposer_notification.id
                    ),
                    "message_id": message.id,
                    "thread_id": thread.id,
                    "extension_id": instance.id,
                },
            )

        # Only the OTHER party receives the action email.
        maybe_queue_email(
            other_party,
            "tenancy.extension.proposed",
        )

        return
    
    
    old_status = getattr(
        instance,
        "_old_status",
        None,
    )
    new_status = instance.status

    if old_status == new_status:
        return

    if new_status == instance.STATUS_ACCEPTED:
        thread, message = create_extension_system_message(
            "tenancy_extension_accepted",
            (
                "Tenancy renewal accepted\n\n"
                f"The renewal for {tenancy.room.title} has been accepted.\n\n"
                f"The new tenancy period starts "
                f"{proposed_start_date_text} and continues "
                f"for {duration_text}."
            ),
        )

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
            if not user:
                continue

            notification, notification_created = (
                Notification.objects.get_or_create(
                    user=user,
                    type="tenancy_extension_accepted",
                    target_type="tenancy_extension",
                    target_id=instance.id,
                    defaults={
                        "thread": thread,
                        "message": message,
                        "audience": audience,
                        "title": "Tenancy renewal accepted",
                        "body": (
                            f"The renewal for "
                            f"{tenancy.room.title} has been "
                            f"accepted. The new tenancy period "
                            f"starts {proposed_start_date_text} "
                            f"and continues for {duration_text}."
                        ),
                    },
                )
            )

            if notification_created and thread and message:
                push_user_realtime_event(
                    user.id,
                    "new_notification",
                    {
                        "kind": "tenancy_extension_accepted",
                        "notification_id": notification.id,
                        "message_id": message.id,
                        "thread_id": thread.id,
                    },
                )

            maybe_queue_email(
                user,
                "tenancy.extension.accepted",
            )

    elif new_status == instance.STATUS_REJECTED:
        proposer = instance.proposed_by

        if not proposer:
            return

        proposer_audience = (
            Notification.Audience.LANDLORD
            if proposer.id == tenancy.landlord_id
            else (
                Notification.Audience.SEEKER
                if proposer.id == tenancy.tenant_id
                else Notification.Audience.BOTH
            )
        )

        thread, message = create_extension_system_message(
            "tenancy_extension_rejected",
            (
                "Tenancy renewal declined\n\n"
                f"The proposed renewal for {tenancy.room.title}, "
                f"starting {proposed_start_date_text} for "
                f"{duration_text}, was declined.\n\n"
                "The existing tenancy information remains unchanged."
            ),
        )

        notification, notification_created = (
            Notification.objects.get_or_create(
                user=proposer,
                type="tenancy_extension_rejected",
                target_type="tenancy_extension",
                target_id=instance.id,
                defaults={
                    "thread": thread,
                    "message": message,
                    "audience": proposer_audience,
                    "title": "Tenancy renewal declined",
                    "body": (
                        f"The proposed renewal for "
                        f"{tenancy.room.title}, starting "
                        f"{proposed_start_date_text} for "
                        f"{duration_text}, was declined. "
                        "The existing tenancy information "
                        "remains unchanged."
                    ),
                },
            )
        )

        if notification_created and thread and message:
            push_user_realtime_event(
                proposer.id,
                "new_notification",
                {
                    "kind": "tenancy_extension_rejected",
                    "notification_id": notification.id,
                    "message_id": message.id,
                    "thread_id": thread.id,
                },
            )

        maybe_queue_email(
            proposer,
            "tenancy.extension.rejected",
        )