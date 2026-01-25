from celery import shared_task
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model

@shared_task
def send_email_task(recipient, subject, body):
    send_mail(
        subject,
        "", 
        'onboarding@resend.dev',
        [recipient],
        html_message=body
    )
    return f"Email sent to {recipient}"

@shared_task
def cleanup_unverified_users_task():
    User = get_user_model()
    threshold = timezone.now() - timedelta(hours=24)
    
    count, _ = User.objects.filter(is_active=False, date_joined__lt=threshold).delete()
    
    return f"Cleaned up {count} unverified users."