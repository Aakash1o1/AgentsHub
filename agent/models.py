from django.db import models
from base.models import BaseModel
from vendor.models import Vendor


# Create your models here.
class Agent(BaseModel):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="agents")

    slug = models.SlugField(max_length=50)
    label = models.CharField(max_length=100)

    description = models.CharField(max_length=255, blank=True)

    prompt_name = models.CharField(max_length=100)

    tools = models.JSONField(default=list, blank=True)

    is_default = models.BooleanField(default=False)

    graph_json = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["vendor", "slug"], name="unique_agent_slug_per_vendor"
            )
        ]

    def __str__(self):
        return f"{self.label} ({self.slug})"
