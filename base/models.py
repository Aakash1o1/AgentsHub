from django.db import models
from django.conf import settings

# This manager makes sure others only get active objects
class ActivateManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)



# Create your models here.
class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(app_label)s_%(class)s_created',
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(app_label)s_%(class)s_updated',
    )

    objects = models.Manager()
    active = ActivateManager()          
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True