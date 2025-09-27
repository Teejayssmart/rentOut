from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Avg, Count

from .models import Review, Room

def _recalc_room_rating(room: Room):
    agg = Review.objects.filter(room=room, active=True).aggregate(
        avg=Avg("rating"),
        cnt=Count("id"),
    )
    room.avg_rating = float(agg["avg"] or 0)
    room.number_rating = int(agg["cnt"] or 0)
    room.save(update_fields=["avg_rating", "number_rating"])

@receiver(post_save, sender=Review)
def review_saved(sender, instance: Review, **kwargs):
    _recalc_room_rating(instance.room)

@receiver(post_delete, sender=Review)
def review_deleted(sender, instance: Review, **kwargs):
    _recalc_room_rating(instance.room)
