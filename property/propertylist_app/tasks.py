from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef
from django.apps import apps
from django.conf import settings

from propertylist_app.models import UserProfile, Room, Review
from propertylist_app.services.tasks import (
    send_new_message_email,
    expire_paid_listings,
)
from propertylist_app.services.reviews import update_room_rating_from_revealed_reviews

# IMPORTANT: ensure nested notification tasks are registered
from propertylist_app.notifications.tasks import notify_completed_viewings  # noqa: F401

from django.db.models import Avg
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
                booking__room=OuterRef("pk"),
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


# -------------------------------------------------------------------
# Tenancy notifications (INBOX ONLY – stable)
# -------------------------------------------------------------------
@shared_task
def task_send_tenancy_notification(tenancy_id: int, event: str) -> int:
    Tenancy = apps.get_model("propertylist_app", "Tenancy")
    Notification = apps.get_model("propertylist_app", "Notification")

    tenancy = (
        Tenancy.objects
        .select_related("room", "landlord", "tenant")
        .filter(id=tenancy_id)
        .first()
    )
    if not tenancy:
        return 0

    if event == "proposed":
        target_user = (
            tenancy.landlord
            if tenancy.proposed_by_id == tenancy.tenant_id
            else tenancy.tenant
        )
        Notification.objects.create(
            user=target_user,
            type="tenancy_proposed",
            title="Tenancy proposal",
            body=f"A tenancy proposal was created for: {tenancy.room.title}. Please respond.",
        )
        return 1

    if event == "confirmed":
        for u in (tenancy.landlord, tenancy.tenant):
            Notification.objects.create(
                user=u,
                type="tenancy_confirmed",
                title="Tenancy confirmed",
                body=f"Tenancy confirmed for: {tenancy.room.title}.",
            )
        return 2

    if event == "cancelled":
        for u in (tenancy.landlord, tenancy.tenant):
            Notification.objects.create(
                user=u,
                type="tenancy_cancelled",
                title="Tenancy cancelled",
                body=f"Tenancy cancelled for: {tenancy.room.title}.",
            )
        return 2

    # updated
    target_user = (
        tenancy.landlord
        if tenancy.proposed_by_id == tenancy.tenant_id
        else tenancy.tenant
    )
    Notification.objects.create(
        user=target_user,
        type="tenancy_updated",
        title="Tenancy updated",
        body=f"Tenancy proposal updated for: {tenancy.room.title}.",
    )
    return 1


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
    count = 0

    # still living check
    due_checks = Tenancy.objects.filter(
        status__in=[Tenancy.STATUS_CONFIRMED, Tenancy.STATUS_ACTIVE],
        still_living_check_at__isnull=False,
        still_living_check_at__lte=now,
        still_living_confirmed_at__isnull=True,
    )

    for t in due_checks:
        for u in (t.landlord, t.tenant):
            Notification.objects.create(
                user=u,
                type="tenancy_still_living_check",
                title="Tenancy check",
                body=f"Is the tenant still living at {t.room.title}?",
            )
            count += 1

    # reviews open
    due_reviews = Tenancy.objects.filter(
        status__in=[Tenancy.STATUS_CONFIRMED, Tenancy.STATUS_ACTIVE, Tenancy.STATUS_ENDED],
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

        if tenant_done and landlord_done:
            continue

        for u in (t.landlord, t.tenant):
            Notification.objects.create(
                user=u,
                type="review_available",
                title="Review available",
                body=f"You can now leave a review for {t.room.title}.",
            )
            count += 1

    # ------------------------------------------------------------------
    # REVEAL EVENT + RATING UPDATE (tenancy-based, not review-flag-based)
    #
    # Requirement: rating updates only after reveal.
    # So we only update rating when:
    # - tenancy is ENDED
    # - review_deadline_at has passed
    #
    # We do NOT rely on Review.is_revealed / revealed_at / is_hidden at all.
    # ------------------------------------------------------------------
    reveal_candidates = Tenancy.objects.filter(
        status=Tenancy.STATUS_ENDED,
        review_deadline_at__isnull=False,
        review_deadline_at__lte=now,
    ).select_related("room")

    for t in reveal_candidates:
        qs = Review.objects.filter(tenancy=t)

        # ignore deleted if your schema supports it
        if any(f.name == "is_deleted" for f in Review._meta.fields):
            qs = qs.filter(is_deleted=False)

        # choose the numeric review rating field that exists in your model
        review_rating_field = None
        for name in ("rating", "stars", "score"):
            if any(f.name == name for f in Review._meta.fields):
                review_rating_field = name
                break

        if not review_rating_field:
            continue

        avg_val = qs.aggregate(avg=Avg(review_rating_field))["avg"]
        if avg_val is None:
            avg_val = 0.0

        # choose the room rating field that exists in your model
        room_rating_field = None
        for name in ("rating", "avg_rating", "average_rating", "room_rating", "review_rating", "score"):
            if any(f.name == name for f in Room._meta.fields):
                room_rating_field = name
                break

        if not room_rating_field:
            continue

        # persist rating
        room = t.room
        setattr(room, room_rating_field, float(avg_val))
        room.save(update_fields=[room_rating_field])

    return count

# -------------------------------------------------------------------
# Tenancy lifecycle + automatic review window
# -------------------------------------------------------------------
from propertylist_app.services.tenancy_dates import (
    compute_end_date,
    compute_review_window,
)


@shared_task
def task_refresh_tenancy_status_and_review_windows():
    Tenancy = apps.get_model("propertylist_app", "Tenancy")

    today = timezone.localdate()

    for t in Tenancy.objects.exclude(status=Tenancy.STATUS_CANCELLED).iterator():
        if t.status == Tenancy.STATUS_CONFIRMED and t.move_in_date <= today:
            t.status = Tenancy.STATUS_ACTIVE

        end_date = compute_end_date(t.move_in_date, t.duration_months)

        if t.status in (Tenancy.STATUS_CONFIRMED, Tenancy.STATUS_ACTIVE) and end_date < today:
            t.status = Tenancy.STATUS_ENDED

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
            t.still_living_check_at = t.still_living_check_at or sl

        t.save()
