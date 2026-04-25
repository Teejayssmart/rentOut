# propertylist_app/api/schema_enums.py

# Keep these as module-level tuples/lists that drf-spectacular can import.
# DO NOT define multiple names for the same exact choice set.

# propertylist_app/api/schema_enums.py

from propertylist_app.models import Review, UserProfile, Payment  # import what you need

# propertylist_app/api/schema_enums.py





# if you created STRIPE_INTENT_STATUS_CHOICES yourself, keep it,
# otherwise point it to the real source too (if you have one).


# if you created STRIPE_INTENT_STATUS_CHOICES yourself, keep it,
# otherwise point it to the real source too (if you have one).



ROOM_STATUS_CHOICES = (
    ("active", "Active"),
    ("hidden", "Hidden"),
    ("draft", "Draft"),
    ("expired", "Expired"),
)

BOOKING_STATUS_CHOICES = (
    ("pending", "Pending"),
    ("confirmed", "Confirmed"),
    ("cancelled", "Cancelled"),
)

REVIEW_ROLE_CHOICES = (
    ("tenant_to_landlord", "Tenant to landlord"),
    ("landlord_to_tenant", "Landlord to tenant"),
)

# If you have many “smoking” fields sharing the same choices,
# define ONE canonical set and reuse it everywhere:
SMOKING_CHOICES = (
    ("yes", "Yes"),
    ("no", "No"),
    ("outside_only", "Outside only"),
)


# propertylist_app/api/schema_enums.py

# Shared yes/no/no_preference choice set used by multiple fields.
YES_NO_NO_PREFERENCE_CHOICES = (
    ("yes", "Yes"),
    ("no", "No"),
    ("no_preference", "No preference"),
)

# Stripe PaymentIntent/Payment status enum (this is your Status65aEnum)
STRIPE_INTENT_STATUS_CHOICES = (
    ("requires_payment_method", "Requires payment"),
    ("requires_action", "Requires action"),
    ("processing", "Processing"),
    ("succeeded", "Succeeded"),
    ("canceled", "Canceled"),
)

# User profile role enum (this is your Role0efEnum)
USER_ROLE_CHOICES = getattr(UserProfile, "ROLE_CHOICES", (("landlord","Landlord"), ("seeker","Seeker")))
REVIEW_ROLE_CHOICES = Review.ROLE_CHOICES  # <-- or whatever your model uses











