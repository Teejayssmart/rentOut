from django.apps import apps
from django.db.models import Avg
from django.db.models.fields import (
    FloatField,
    DecimalField,
    IntegerField,
    SmallIntegerField,
    PositiveIntegerField,
    PositiveSmallIntegerField,
)

_NUMERIC_FIELD_TYPES = (
    FloatField,
    DecimalField,
    IntegerField,
    SmallIntegerField,
    PositiveIntegerField,
    PositiveSmallIntegerField,
)


def _is_real_model_field(model, name: str) -> bool:
    try:
        model._meta.get_field(name)
        return True
    except Exception:
        return False


def _pick_numeric_field(model, preferred_names):
    for name in preferred_names:
        if _is_real_model_field(model, name):
            f = model._meta.get_field(name)
            if isinstance(f, _NUMERIC_FIELD_TYPES):
                return name

    for f in model._meta.fields:
        if isinstance(f, _NUMERIC_FIELD_TYPES):
            n = f.name.lower()
            if "rating" in n or "score" in n:
                return f.name

    return None


def _revealed_only_filter(qs, Review):
    if _is_real_model_field(Review, "is_revealed"):
        return qs.filter(is_revealed=True)

    if _is_real_model_field(Review, "revealed_at"):
        return qs.filter(revealed_at__isnull=False)

    if _is_real_model_field(Review, "is_hidden"):
        return qs.filter(is_hidden=False)

    # if we can't detect reveal fields, do not drop rows
    return qs


def _reviews_for_room(room, Review):
    """
    Support both schemas:
    - Review.room FK exists -> filter by room_id
    - Review has no room FK but has tenancy FK -> filter by tenancy__room_id
    """
    if _is_real_model_field(Review, "room"):
        return Review.objects.filter(room_id=room.id)

    if _is_real_model_field(Review, "tenancy"):
        return Review.objects.filter(tenancy__room_id=room.id)

    # worst case: no linkage we can use
    return Review.objects.none()


def update_room_rating_from_revealed_reviews(room) -> bool:
    """
    Recalculate room rating using revealed reviews only.
    Returns True if it updated a real Room DB field, else False.
    """
    Review = apps.get_model("propertylist_app", "Review")
    Room = apps.get_model("propertylist_app", "Room")

    qs = _reviews_for_room(room, Review)

    if _is_real_model_field(Review, "is_deleted"):
        qs = qs.filter(is_deleted=False)

    qs = _revealed_only_filter(qs, Review)

    review_rating_field = _pick_numeric_field(
        Review,
        preferred_names=("rating", "stars", "score"),
    )
    if not review_rating_field:
        return False

    avg_val = qs.aggregate(avg=Avg(review_rating_field))["avg"]
    if avg_val is None:
        avg_val = 0.0

    room_rating_field = _pick_numeric_field(
        Room,
        preferred_names=("rating", "avg_rating", "average_rating", "room_rating", "review_rating", "score"),
    )
    if not room_rating_field:
        return False

    setattr(room, room_rating_field, float(avg_val))
    room.save(update_fields=[room_rating_field])
    return True
