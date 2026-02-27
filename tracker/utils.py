import logging
import resend
from django.conf import settings

logger = logging.getLogger(__name__)


def is_json_request(request):
    """Returns True only if the client explicitly asks for JSON (Postman/API)."""
    accept = request.META.get('HTTP_ACCEPT', '')
    content_type = request.META.get('CONTENT_TYPE', '')
    return 'application/json' in accept or 'application/json' in content_type


def send_async_email(to_email: str, subject: str, html_content: str) -> bool:
    """
    Sends an email via Resend HTTP API.

    In production: uses Resend (fast HTTP call, reliable, no SMTP timeout).
    In dev (DEBUG=True): falls back to Django's configured email backend (Gmail SMTP).

    Returns True on success, False on failure (never raises — safe to call anywhere).
    """
    if settings.DEBUG:
        # Dev fallback — use whatever Django email backend is configured
        try:
            from django.core.mail import EmailMultiAlternatives
            msg = EmailMultiAlternatives(
                subject=subject,
                body="Please view this email in an HTML-compatible client.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to_email],
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)
            return True
        except Exception as e:
            logger.error("Dev email failed to %s: %s", to_email, e)
            return False

    # Production — Resend HTTP API
    try:
        resend.api_key = settings.RESEND_API_KEY
        if not resend.api_key:
            logger.error("RESEND_API_KEY is not set — email not sent to %s", to_email)
            return False

        resend.Emails.send({
            "from": settings.DEFAULT_FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        })
        return True

    except Exception as e:
        logger.error("Resend email failed to %s: %s", to_email, e)
        return False