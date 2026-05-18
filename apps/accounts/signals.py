from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=User)
def ensure_profile(sender, instance: User, created: bool, **kwargs):
    if created:
        UserProfile.objects.create(
            user=instance,
            role=UserProfile.ROLE_ADMIN if instance.is_superuser else UserProfile.ROLE_STAFF,
        )
    elif not hasattr(instance, "profile"):
        UserProfile.objects.create(user=instance)
