from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower  # fix: needed for UniqueConstraint on Lower()



class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):   return self.filter(is_deleted=False)
    def dead(self):    return self.filter(is_deleted=True)


class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        abstract = True

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])


class RoomCategorie(models.Model):
    key = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=30)
    about = models.TextField(max_length=150)
    website = models.URLField(max_length=100)

    def __str__(self):
        return self.name


class Room(SoftDeleteModel):
    title = models.CharField(max_length=200)
    description = models.TextField()
    price_per_month = models.DecimalField(max_digits=8, decimal_places=2)
    location = models.CharField(max_length=255)
    category = models.ForeignKey(RoomCategorie, on_delete=models.CASCADE, related_name="room_info")
    available_from = models.DateField()
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    furnished = models.BooleanField(default=False)
    bills_included = models.BooleanField(default=False)
    property_owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="rooms")
    image = models.ImageField(upload_to='room_images/', null=True, blank=True)
    number_of_bedrooms = models.IntegerField()
    number_of_bathrooms = models.IntegerField()
    property_type = models.CharField(max_length=100, choices=[
        ('flat', 'Flat'),
        ('house', 'House'),
        ('studio', 'Studio'),
    ])
    parking_available = models.BooleanField(default=False)
    avg_rating = models.FloatField(default=0)
    number_rating = models.IntegerField(default=0)

    def clean(self):
        super().clean()
        if self.bills_included and self.price_per_month is not None and float(self.price_per_month) < 100.0:
            raise ValidationError({"bills_included": "Bills cannot be included for such a low price."})

    class Meta:
        constraints = [
            # fix: remove bad/undefined fields constraint; keep valid functional unique constraint
            models.UniqueConstraint(Lower('title'), name='uq_room_title_lower'),
        ]

    def __str__(self):
        return self.title


class Review(models.Model):
    review_user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    description = models.CharField(max_length=200, null=True)
    created = models.DateTimeField(auto_now_add=True)   # fix: remove duplicate definition
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="reviews")
    active = models.BooleanField(default=True)
    update = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.rating) + " | " + self.room.title + " | " + str(self.review_user)


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    # E.164 numbers are up to 15 digits after '+'
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} profile"


class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=200)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    extra_data = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"{self.timestamp} - {self.user} - {self.action}"







class IdempotencyKey(models.Model):
    user_id = models.IntegerField(db_index=True)
    key = models.CharField(max_length=200, db_index=True)
    action = models.CharField(max_length=100)  # e.g., "create_booking" / "charge_card"
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user_id", "key", "action")


class RoomImage(models.Model):
    room = models.ForeignKey('Room', on_delete=models.PROTECT) 
    image = models.ImageField(upload_to='room_images/', null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Photo {self.id} for {self.room.title}"
    


class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookings")
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="bookings")
    start = models.DateTimeField()
    end = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["room", "start", "end"]),
        ]

class WebhookReceipt(models.Model):
    source = models.CharField(max_length=50, db_index=True)  # e.g. "provider"
    event_id = models.CharField(max_length=255, unique=True) # used for replay protection
    received_at = models.DateTimeField(auto_now_add=True)


