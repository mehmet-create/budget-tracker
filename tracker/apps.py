from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _
class TrackerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tracker'
    
    def ready(self):
        import tracker.signals