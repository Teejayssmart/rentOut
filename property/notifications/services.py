from urllib.parse import quote

from django.template import Template, Context
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from .models import NotificationTemplate, OutboundNotification, DeliveryAttempt


def send_mail(subject, message, from_email, recipient_list, *, html_message=None):
    """
    Single wrapper used across the project.
    - Keeps the classic signature your tasks/tests expect.
    - Adds optional html_message support.
    """
    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=from_email,
        to=recipient_list,
    )

    if html_message:
        email.attach_alternative(html_message, "text/html")

    return email.send()


def _safe_next_path(next_path: str | None, default: str = "/inbox") -> str:
    """
    Prevent open-redirects. Only allow internal paths like '/inbox?...'.
    """
    if not next_path or not isinstance(next_path, str):
        return default
    next_path = next_path.strip()
    if not next_path.startswith("/"):
        return default
    return next_path


def _frontend_base() -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "") or ""
    return base.rstrip("/")


def build_login_redirect_url(next_path: str | None = "/inbox") -> str:
    """
    Returns: '{FRONTEND_BASE_URL}/login?next=/inbox...'
    """
    base = _frontend_base()
    safe_next = _safe_next_path(next_path, default="/inbox")
    # keep common URL chars safe (so '/inbox?focus=thread&id=1' stays readable)
    return f"{base}/login?next={quote(safe_next, safe='/?:&=')}"


class EmailTransport:
    @staticmethod
    def send(to_email: str, subject: str, body: str, *, html_message: str | None = None):
        """
        Email sending transport.
        Uses EMAIL_BACKEND configured in settings.
        """
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@rentout.co.uk"
        sent = send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=[to_email],
            html_message=html_message,
        )
        return {"sent": sent}


class NotificationService:
    @staticmethod
    def _enrich_context(context_dict: dict) -> dict:
        """
        Adds standard context keys so templates can link safely back to the app.

        Supported inputs:
        - context['next_path'] (preferred): '/inbox?...'
        - context['frontend_path']         : '/inbox?...'
        - context['url']                   : if it's a relative path '/something', we treat it as next_path
        """
        ctx = dict(context_dict or {})

        base = _frontend_base()
        ctx.setdefault("frontend_base_url", base)

        # determine next path from common keys
        next_path = (
            ctx.get("next_path")
            or ctx.get("frontend_path")
            or (ctx.get("url") if isinstance(ctx.get("url"), str) and ctx.get("url", "").startswith("/") else None)
        )

        next_path = _safe_next_path(next_path, default="/inbox")

        # provide standard CTA URLs for templates
        ctx.setdefault("next_path", next_path)
        ctx.setdefault("cta_url", build_login_redirect_url(next_path))
        ctx.setdefault("inbox_url", build_login_redirect_url("/inbox"))

        return ctx

    @staticmethod
    def render(template_obj: NotificationTemplate, context_dict: dict):
        subject_tpl = Template(template_obj.subject or "")
        body_tpl = Template(template_obj.body or "")
        ctx = Context(NotificationService._enrich_context(context_dict or {}))
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
        # Preferences (leave as you originally intended)
        prefs = getattr(notification.user, "notification_pref", None)
        if notification.channel == "email" and prefs and not prefs.email_enabled:
            notification.status = OutboundNotification.STATUS_SKIPPED
            notification.sent_at = timezone.now()
            notification.save(update_fields=["status", "sent_at"])
            return

        tpl = NotificationTemplate.objects.filter(
            key=notification.template_key,
            channel=notification.channel,
            is_active=True,
        ).first()

        if not tpl:
            notification.status = OutboundNotification.STATUS_FAILED
            notification.error = f"Template not found: {notification.template_key}"
            notification.save(update_fields=["status", "error"])
            return

        # render now injects cta_url/inbox_url/next_path/frontend_base_url
        subject, body = NotificationService.render(tpl, notification.context)

        try:
            if notification.channel == "email":
                res = EmailTransport.send(notification.user.email, subject, body)
            else:
                res = {"sent": 0}

            DeliveryAttempt.objects.create(
                notification=notification,
                provider=notification.channel,
                success=bool(res.get("sent")),
                response=str(res),
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
                notification=notification,
                provider=notification.channel,
                success=False,
                response=str(exc),
            )
            notification.status = OutboundNotification.STATUS_FAILED
            notification.error = str(exc)
            notification.save(update_fields=["status", "error"])