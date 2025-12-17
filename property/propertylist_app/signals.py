from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Avg, Count

from .models import Message, Notification, MessageThread
from .models import Review, Room

from propertylist_app.tasks import task_send_new_message_email


def _recalc_room_rating(room: Room):
    """
    Room rating is now derived from BOOKING-based reviews.
    """
    agg = Review.objects.filter(
        booking__room=room,
        active=True,
    ).aggregate(
        avg=Avg("overall_rating"),
        cnt=Count("id"),
    )

    room.avg_rating = float(agg["avg"] or 0)
    room.number_rating = int(agg["cnt"] or 0)
    room.save(update_fields=["avg_rating", "number_rating"])


@receiver(post_delete, sender=Review)
def review_deleted(sender, instance: Review, **kwargs):
    room = getattr(getattr(instance, "booking", None), "room", None)
    if room is not None:
        _recalc_room_rating(room)


@receiver(post_save, sender=Review)
def review_saved(sender, instance: Review, **kwargs):
    room = getattr(getattr(instance, "booking", None), "room", None)
    if room is not None:
        _recalc_room_rating(room)


@receiver(post_save, sender=Message)
def message_created_create_notifications(sender, instance: Message, created, **kwargs):
    """
    When a new message is created, notify all other participants in the thread.
    """
    if not created:
        return

    thread: MessageThread = instance.thread
    recipients = thread.participants.exclude(pk=instance.sender_id).all()

    notifs = []
    for user in recipients:
        notifs.append(
            Notification(
                user=user,
                type=Notification.Type.MESSAGE,
                thread=thread,
                message=instance,
                title="New message",
                body=(instance.body[:200] or ""),
            )
        )

    if notifs:
        Notification.objects.bulk_create(notifs, ignore_conflicts=True)
