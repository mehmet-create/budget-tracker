import logging
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.conf import settings

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def send_email_task(self, to_email, subject, html_content):
    """
    Standard Synchronous Celery Task.
    No 'async', no 'await'. Just standard Python.
    """
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body="Please view this email in a generic HTML client.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email]
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        
        logger.info(f"Email sent successfully to {to_email}")
        return f"Email sent to {to_email}"
        
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        raise self.retry(exc=e, countdown=60)