from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template import Context, Template
from django.utils import timezone

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





def _frontend_base_url() -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "") or ""
    return base.rstrip("/")


def _safe_next_path(next_path: str | None, default: str = "/inbox") -> str:
    """
    Security: prevent open redirect.
    Only allow internal paths that start with '/'.
    """
    if not next_path or not isinstance(next_path, str):
        return default
    next_path = next_path.strip()
    if not next_path.startswith("/"):
        return default
    return next_path





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



def send_security_code_email(
    *,
    to_email: str,
    subject: str,
    first_name: str = "",
    title: str,
    intro: str,
    code: str,
    expiry_minutes: int | None = None,
):
    """
    Sends branded RentCrib security/OTP emails.
    Keeps a plain-text fallback so existing tests can still find the 6-digit code.
    """
    expiry_text = f"This code expires in {expiry_minutes} minutes." if expiry_minutes else "This code will expire shortly."

    text_body = (
        f"Hi {first_name or 'there'},\n\n"
        f"{intro}\n\n"
        f"Your code is: {code}\n\n"
        f"{expiry_text}\n\n"
        "If you did not request this, you can safely ignore this email.\n\n"
        "RentCrib"
    )

    html_body = Template("""
{% extends "emails/base.html" %}

{% block content %}

<h2 style="font-family:Arial,sans-serif;color:#333333;">
{{ title }}
</h2>

<p>
Hi {{ first_name|default:"there" }},
</p>

<p>
{{ intro }}
</p>

<p style="
font-size:32px;
font-weight:700;
letter-spacing:6px;
text-align:center;
background:#f5f7fb;
padding:18px;
border-radius:10px;
font-family:Arial,sans-serif;
color:#357af0;
">
{{ code }}
</p>

<p>
{{ expiry_text }}
</p>

<p style="color:#666666;">
If you did not request this, you can safely ignore this email.
</p>

<p>
Thank you for using RentCrib.
</p>

{% endblock %}
""").render(Context({
        "title": title,
        "first_name": first_name or "",
        "intro": intro,
        "code": code,
        "expiry_text": expiry_text,
    }))

    return EmailTransport.send(
        to_email,
        subject,
        text_body,
        html_message=html_body,
    )



def _direct_cta_url(cta_url: str | None, next_path: str) -> str:
    """
    Build a direct RentCrib frontend CTA.

    Authentication is handled by the frontend/app session.
    Email links must not force authenticated users through /login.

    - Relative internal paths become absolute frontend URLs.
    - Absolute frontend URLs stay unchanged.
    - External URLs stay unchanged.
    - If no CTA is supplied, fall back to the safe internal next_path.
    """
    base = _frontend_base_url()

    if not cta_url:
        safe_next = _safe_next_path(next_path, default="/inbox")
        return f"{base}{safe_next}"

    value = str(cta_url).strip()

    if value.startswith("/"):
        return f"{base}{value}"

    return value

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
        ctx["cta_url"] = _direct_cta_url(
            ctx.get("cta_url"),
            next_path,
        )
        ctx.setdefault("inbox_url", f"{base}/messages")

        return ctx

    @staticmethod
    def render(template_obj: NotificationTemplate, context_dict: dict):
        """
        Adds standard URL context for email templates:
        - next_path: internal path like '/inbox?...'
        - cta_url:   direct frontend URL for the intended destination
        - inbox_url: direct frontend messages/inbox URL
        - frontend_base_url: base frontend domain
        """
        context_dict = dict(context_dict or {})

        # Try to discover the deep-link path from context.
        # We support a few common keys so we don't break existing notifications.
        next_path = (
            context_dict.get("next_path")
            or context_dict.get("frontend_path")
            or context_dict.get("path")
            or (
                context_dict.get("url")
                if isinstance(context_dict.get("url"), str) and context_dict["url"].startswith("/")
                else None
            )
        )
        next_path = _safe_next_path(next_path, default="/inbox")

        # Inject new keys that templates can use.
        context_dict.setdefault("frontend_base_url", _frontend_base_url())
        context_dict.setdefault("next_path", next_path)
        context_dict["cta_url"] = _direct_cta_url(
            context_dict.get("cta_url"),
            next_path,
        )
        context_dict.setdefault(
            "inbox_url",
            f"{_frontend_base_url()}/messages",
        )

        subject_tpl = Template(template_obj.subject or "")
        body_tpl = Template(template_obj.body or "")
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
        """
        Deliver one queued notification.

        Lock the database row before sending so two Celery workers cannot
        deliver the same notification at the same time.
        """
        notification = (
            OutboundNotification.objects
            .select_for_update()
            .select_related("user")
            .get(pk=notification.pk)
        )

        # Another worker may have delivered this notification while this
        # worker was waiting for the row lock.
        if notification.status in {
            OutboundNotification.STATUS_SENT,
            OutboundNotification.STATUS_SKIPPED,
        }:
            return

        prefs = getattr(notification.user, "notification_pref", None)

        if (
            notification.channel == NotificationTemplate.CHANNEL_EMAIL
            and prefs
            and not prefs.email_enabled
        ):
            notification.status = OutboundNotification.STATUS_SKIPPED
            notification.sent_at = timezone.now()
            notification.save(
                update_fields=[
                    "status",
                    "sent_at",
                ]
            )
            return

        tpl = NotificationTemplate.objects.filter(
            key=notification.template_key,
            channel=notification.channel,
            is_active=True,
        ).first()

        if not tpl:
            notification.status = OutboundNotification.STATUS_FAILED
            notification.error = f"Template not found: {notification.template_key}"
            notification.save(
                update_fields=[
                    "status",
                    "error",
                ]
            )
            return

        try:
            subject, body = NotificationService.render(
                tpl,
                notification.context,
            )

            if notification.channel == NotificationTemplate.CHANNEL_EMAIL:
                res = EmailTransport.send(
                    notification.user.email,
                    subject,
                    body,
                    html_message=body,
                )
            else:
                res = {"sent": 0}

            sent = bool(res.get("sent"))

            DeliveryAttempt.objects.create(
                notification=notification,
                provider=notification.channel,
                success=sent,
                response=str(res),
            )

            if sent:
                notification.status = OutboundNotification.STATUS_SENT
                notification.sent_at = timezone.now()
                notification.error = ""
                notification.save(
                    update_fields=[
                        "status",
                        "sent_at",
                        "error",
                    ]
                )
                return

            notification.status = OutboundNotification.STATUS_FAILED
            notification.error = "Provider reported failure"
            notification.save(
                update_fields=[
                    "status",
                    "error",
                ]
            )

        except Exception as exc:
            error_message = str(exc)

            DeliveryAttempt.objects.create(
                notification=notification,
                provider=notification.channel,
                success=False,
                response=error_message,
            )

            notification.status = OutboundNotification.STATUS_FAILED
            notification.error = error_message
            notification.save(
                update_fields=[
                    "status",
                    "error",
                ]
            )