from django.db import models
from django.contrib.auth.models import AbstractUser

from vendor.models import Vendor
# Create your models here.
class User(AbstractUser):
    phone = models.CharField(max_length=20, blank=True)
    active_vendor = models.ForeignKey(
        "vendor.Vendor",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="active_users",
    )
    vendors = models.ManyToManyField(Vendor, related_name="users", blank=True)
    keycloak_id = models.CharField(max_length=36, unique=True, null=True, blank=True)
