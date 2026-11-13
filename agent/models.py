from django.db import models
from base.models import BaseModel
from vendor.models import Vendor
from agent.services.workflow import AgentWorkflow


# Create your models here.
class Agent(BaseModel):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="agents")

    slug = models.SlugField(max_length=50)
    label = models.CharField(max_length=100)

    description = models.CharField(max_length=255, blank=True)

    is_default = models.BooleanField(default=False)

    workflow_json = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["vendor", "slug"], name="unique_agent_slug_per_vendor"
            )
        ]

    @property
    def workflow(self):
        return AgentWorkflow(self.workflow_json)

    def __str__(self):
        return f"{self.label} ({self.slug})"
