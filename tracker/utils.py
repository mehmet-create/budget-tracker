import threading
from django.core.mail import EmailMultiAlternatives
from django.conf import settings


def is_json_request(request):
    """Returns True only if the client explicitly asks for JSON (Postman/API)."""
    accept = request.META.get('HTTP_ACCEPT', '')
    content_type = request.META.get('CONTENT_TYPE', '')
    return 'application/json' in accept or 'application/json' in content_type


def send_async_email(to_email, subject, html_content):
    """
    Sends an email in a background thread so the request isn't blocked.
    Uses whatever EMAIL_BACKEND is configured in settings.py
    (Gmail SMTP in dev, Resend SMTP in production).
    No Celery or Redis required.
    """
    def _send():
        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body="Please view this email in an HTML-compatible client.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to_email],
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)
        except Exception as e:
            # Log but don't crash the calling request
            import logging
            logging.getLogger(__name__).error("Email send failed to %s: %s", to_email, e)

    threading.Thread(target=_send, daemon=True).start()