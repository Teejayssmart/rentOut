from django.template import Template, Context
from django.core.mail import send_mail as django_send_mail
from django.utils import timezone
from django.db import transaction
from django.conf import settings



from .models import NotificationTemplate, OutboundNotification, DeliveryAttempt

class EmailTransport:
    @staticmethod
    def send(to_email: str, subject: str, body: str):
        # Uses EMAIL_BACKEND from settings.py (console backend now; SMTP later)
        sent = send_mail(subject=subject, message=body, from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None), recipient_list=[to_email])
        return {"sent": sent}

class NotificationService:
    @staticmethod
    def render(template_obj: NotificationTemplate, context_dict: dict):
        subject_tpl = Template(template_obj.subject or "")
        body_tpl = Template(template_obj.body)
        ctx = Context(context_dict)
        return subject_tpl.render(ctx), body_tpl.render(ctx)

    @staticmethod
    def queue(user, template_key: str, context: dict, scheduled_for=None, channel="email"):
        scheduled_for = scheduled_for or timezone.now()
        return OutboundNotification.objects.create(
            user=user,
            template_key=template_key,
            context=context,
            scheduled_for=scheduled_for,
            channel=channel,
        )

    @staticmethod
    @transaction.atomic
    def deliver(notification: OutboundNotification):
        # Preferences
        prefs = getattr(notification.user, "notification_pref", None)
        if notification.channel == "email" and prefs and not prefs.email_enabled:
            notification.status = OutboundNotification.STATUS_SKIPPED
            notification.sent_at = timezone.now()
            notification.save(update_fields=["status", "sent_at"])
            return

        tpl = NotificationTemplate.objects.filter(
            key=notification.template_key,
            channel=notification.channel,
            is_active=True
        ).first()

        if not tpl:
            notification.status = OutboundNotification.STATUS_FAILED
            notification.error = f"Template not found: {notification.template_key}"
            notification.save(update_fields=["status", "error"])
            return

        subject, body = NotificationService.render(tpl, notification.context)

        try:
            if notification.channel == "email":
                res = EmailTransport.send(notification.user.email, subject, body)
            else:
                res = {"sent": 0}  # push later

            DeliveryAttempt.objects.create(
                notification=notification, provider=notification.channel,
                success=bool(res.get("sent")), response=str(res)
            )

            if res.get("sent"):
                notification.status = OutboundNotification.STATUS_SENT
                notification.sent_at = timezone.now()
                notification.save(update_fields=["status", "sent_at"])
            else:
                notification.status = OutboundNotification.STATUS_FAILED
                notification.error = "Provider reported failure"
                notification.save(update_fields=["status", "error"])
        except Exception as exc:
            DeliveryAttempt.objects.create(
                notification=notification, provider=notification.channel,
                success=False, response=str(exc)
            )
            notification.status = OutboundNotification.STATUS_FAILED
            notification.error = str(exc)
            notification.save(update_fields=["status", "error"])


    

    # --- TOP-LEVEL WRAPPER (must be at column 0) ---
def send_mail(subject, body, from_email=None, recipient_list=None, **kwargs):
    """
    Wrapper so tests can patch `notifications.services.send_mail`.
    Returns number of successfully delivered messages (Django behaviour).
    """
    if not recipient_list:
        return 0
    sender = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@rentout.co.uk")
    return django_send_mail(subject, body, sender, recipient_list, fail_silently=True)


class EmailTransport:
    @staticmethod
    def send(to_email: str, subject: str, body: str):
        # Use the wrapper so tests can patch this call path.
        return {"sent": send_mail(subject=subject, body=body, from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None), recipient_list=[to_email])}
