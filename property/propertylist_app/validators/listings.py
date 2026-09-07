from django.core.exceptions import ValidationError


def assert_not_duplicate_listing(
    user,
    *,
    title: str,
    queryset,
    location: str | None = None,
    exclude_pk: int | None = None,
) -> bool:
    """
    Guard against duplicate live listing titles across RentCrib.

    Titles are globally unique, case-insensitively, for non-deleted listings.
    The database constraint remains the final safety net; this validator turns
    the normal user-correctable case into a clear field-level 400 response
    before an IntegrityError can occur.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required.")

    qs = queryset.filter(
        is_deleted=False,
        title__iexact=(title or "").strip(),
    )

    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    if qs.exists():
        raise ValidationError(
            {
                "title": (
                    "A listing with this title already exists. "
                    "Please choose a different title."
                )
            }
        )

    return True
