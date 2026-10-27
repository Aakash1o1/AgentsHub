from django.db import models
from base.models import BaseModel
from django.utils.text import slugify

# Create your models here.
class Vendor(BaseModel):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:# generate if empty
            self.slug = slugify(self.name) # "Acme Supplies" -> "acme-supplies"
        super().save(*args, **kwargs)
        # This ensures that details used is updated correctly


    def __str__(self):
        return self.name#When we need to print this model as text, this fn will be called
        # it is usefull in logs