from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from .models import UserProfile

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """Creates a UserProfile when a new User is created."""
    if created:
        UserProfile.objects.create(user=instance)
    instance.userprofile.save()