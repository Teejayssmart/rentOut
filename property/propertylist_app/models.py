from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify  # ⟵ add near your other imports
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower  # fix: needed for UniqueConstraint on Lower()
from django.db.models import Q, F




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

    # NEW
    slug = models.SlugField(max_length=40, unique=True, null=True, blank=True, db_index=True)

    active = models.BooleanField(default=True, db_index=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # auto-generate slug from name if not provided
        if not self.slug:
            base = slugify(self.name) or slugify(self.key)
            candidate = base
            i = 2
            while RoomCategorie.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{i}"
                i += 1
            self.slug = candidate
        super().save(*args, **kwargs)


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
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    

    def clean(self):
        super().clean()
        if self.bills_included and self.price_per_month is not None and float(self.price_per_month) < 100.0:
            raise ValidationError({"bills_included": "Bills cannot be included for such a low price."})

    class Meta:
        constraints = [
            # enforce uniqueness of LOWER(title) **only** for non-deleted rows
            models.UniqueConstraint(
                Lower('title'),
                condition=models.Q(is_deleted=False),
                name='uq_room_title_lower_alive',
            ),
        ]

    def __str__(self):
        return self.title


class Review(models.Model):
    review_user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    description = models.CharField(max_length=200, null=True)
    created = models.DateTimeField(auto_now_add=True)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="reviews")
    active = models.BooleanField(default=True)
    update = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]
        constraints = [
            # one review per (room, user)
            models.UniqueConstraint(fields=["room", "review_user"], name="uq_review_once_per_room"),
        ]
        indexes = [
            models.Index(fields=["room", "review_user"]),
            models.Index(fields=["room", "created"]),
        ]

    def __str__(self):
        return f"{self.rating} | {self.room.title} | {self.review_user}"



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
    
# imports at the top of models.py (make sure these two exist)
from django.db import models


class AvailabilitySlot(models.Model):
    room = models.ForeignKey(
        "Room",
        related_name="availability_slots",
        on_delete=models.CASCADE,
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    max_bookings = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("start",)
        constraints = [
            # end must be strictly after start
            models.CheckConstraint(
                check=Q(end__gt=F("start")),
                name="slot_end_after_start",
            ),
            # capacity must be >= 1
            models.CheckConstraint(
                check=Q(max_bookings__gte=1),
                name="slot_max_bookings_gte_1",
            ),
            # avoid duplicate identical slots for the same room
            models.UniqueConstraint(
                fields=["room", "start", "end"],
                name="unique_slot_room_start_end",
            ),
        ]

    def __str__(self):
        return f"{self.room} | {self.start:%Y-%m-%d %H:%M} → {self.end:%Y-%m-%d %H:%M} (cap {self.max_bookings})"


class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookings")
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="bookings")
    slot = models.ForeignKey(AvailabilitySlot, on_delete=models.PROTECT, related_name="bookings", null=True, blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    canceled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["room", "start", "end"]),
        ]

class WebhookReceipt(models.Model):
    source = models.CharField(max_length=50, db_index=True)  # e.g. "provider"
    event_id = models.CharField(max_length=255, unique=True) # used for replay protection
    received_at = models.DateTimeField(auto_now_add=True)


class SavedRoom(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_rooms_links")
    room = models.ForeignKey("Room", on_delete=models.CASCADE, related_name="saved_by_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "room")
        indexes = [
            models.Index(fields=["user", "room"]),
            models.Index(fields=["room"]),
        ]

   
    def __str__(self):
        return f"{getattr(self.user, 'username', 'user')} → {getattr(self, 'room_id', '∅')}"
    
    
    
class MessageThread(models.Model):
    participants = models.ManyToManyField(User, related_name="message_threads")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        users = ", ".join(self.participants.values_list("username", flat=True)[:2])
        return f"Thread {self.id} ({users}…)" 


class Message(models.Model):
    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_messages")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["thread", "created_at"]),
        ]

