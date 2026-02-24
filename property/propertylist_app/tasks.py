from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q
from django.apps import apps
from django.conf import settings

from propertylist_app.models import UserProfile, Room, Review
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
            Q(booking__room=OuterRef("pk")) | Q(tenancy__room=OuterRef("pk")),
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
            target_type="tenancy",
            target_id=tenancy.id,
        )
        return 1

    if event == "confirmed":
        for u in (tenancy.landlord, tenancy.tenant):
            Notification.objects.create(
                user=u,
                type="tenancy_confirmed",
                title="Tenancy confirmed",
                body=f"Tenancy confirmed for: {tenancy.room.title}.",
                target_type="tenancy",
                target_id=tenancy.id,
            )
        return 2

    if event == "cancelled":
        for u in (tenancy.landlord, tenancy.tenant):
            Notification.objects.create(
                user=u,
                type="tenancy_cancelled",
                title="Tenancy cancelled",
                body=f"Tenancy cancelled for: {tenancy.room.title}.",
                target_type="tenancy",
                target_id=tenancy.id,
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
        target_type="tenancy",
        target_id=tenancy.id,
    )
    return 1


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
    count = 0

    # -------------------------------------------------
    # 1) still living check -> notifications
    # -------------------------------------------------
    # still living check
    due_checks = Tenancy.objects.filter(
        status__in=[Tenancy.STATUS_CONFIRMED, Tenancy.STATUS_ACTIVE],
        still_living_check_at__isnull=False,
        still_living_check_at__lte=now,
        still_living_confirmed_at__isnull=True,
    )

    for t in due_checks:
        landlord_done = bool(getattr(t, "still_living_landlord_confirmed_at", None))
        tenant_done = bool(getattr(t, "still_living_tenant_confirmed_at", None))

        # if both confirmed, close it out and stop prompting
        if landlord_done and tenant_done:
            if getattr(t, "still_living_confirmed_at", None) is None:
                t.still_living_confirmed_at = now
                t.save(update_fields=["still_living_confirmed_at"])
            continue

        # notify only the side(s) that have NOT confirmed
        if not landlord_done:
            Notification.objects.create(
                user=t.landlord,
                type="tenancy_still_living_check",
                title="Tenancy check",
                body=f"Is the tenant still living at {t.room.title}?",
                target_type="still_living_check",
                target_id=t.id
            )
            count += 1

        if not tenant_done:
            Notification.objects.create(
                user=t.tenant,
                type="tenancy_still_living_check",
                title="Tenancy check",
                body=f"Is the tenant still living at {t.room.title}?",
                target_type="still_living_check",
                target_id=t.id,
            )
            count += 1

    # -------------------------------------------------
    # 2) reviews open -> notifications (if any side missing)
    # -------------------------------------------------
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
                target_type="tenancy_review",
                target_id=t.id
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
    to_reveal = Review.objects.filter(
        active=False,
        reveal_at__isnull=False,
        reveal_at__lte=now,
    )

    revealed_count = to_reveal.update(active=True)
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
                booking__isnull=True,          # exclude booking reviews
                role=Review.ROLE_TENANT_TO_LANDLORD,  #  only tenant -> landlord affects room rating
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
