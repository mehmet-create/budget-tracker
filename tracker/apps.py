from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _
class TrackerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tracker'
    
    def ready(self):
        import logging
        import tracker.signals
        from django.conf import settings
        
        logger = logging.getLogger(__name__)
        provider = getattr(settings, 'EMAIL_PROVIDER', 'unknown')
        host = getattr(settings, 'EMAIL_HOST', 'not-set')
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'not-set')
        logger.info(f"✓ BudgetApp initialized | Email Provider: {provider} | Host: {host} | From: {from_email}")