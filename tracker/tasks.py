import logging
import os
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage

from . import services, schemas

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


@shared_task(bind=True, max_retries=2)
def import_transactions_task(self, user_id, storage_path):
    try:
        with default_storage.open(storage_path, "rb") as stored_file:
            uploaded_file = File(stored_file, name=os.path.basename(storage_path))
            dto = schemas.ImportTransactionsDTO(user_id=user_id, file=uploaded_file)
            count = services.import_transactions_service(dto)
            logger.info("Imported %s transactions for user_id=%s", count, user_id)
            return count
    except Exception as e:
        logger.exception("Failed to import transactions for user_id=%s", user_id)
        raise self.retry(exc=e, countdown=30)
    finally:
        try:
            default_storage.delete(storage_path)
        except Exception:
            logger.warning("Failed to delete uploaded import file: %s", storage_path)