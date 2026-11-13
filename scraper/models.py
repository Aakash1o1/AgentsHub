import os
from django.db import models
from base.models import BaseModel
from vendor.models import Vendor
from pgvector.django import VectorField

# Create your models here.
class Document(BaseModel):
    STATUS_CHOICES=[
        ("pending","Pending"),
        ("queued","Queued"),
        ("scheduled","Scheduled"),
        ("processing","Processing"),
        ("extracting","Extracting"),
        ("embedding","Embedding"),
        ("completed","Completed"),
        ("error","Error")
    ]

    SOURCE_CHOICES = [
        ("text", "Text file"),
        ("pdf", "PDF"),
        ("website", "Website"),
    ]
    MESSAGE_SCHEMA_VERSION = 1
    def as_message(self):
        return {
            "schema_version": self.MESSAGE_SCHEMA_VERSION,
            "document_id": self.id,
            "vendor_id": self.vendor_id,
            "source_type": self.source_type,
            "url": self.url,
            "file_name": self.file.name or "",
        }



    url = models.URLField(blank=True)
    file = models.FileField(upload_to="documents/%Y/%m/", blank=True)
    status = models.CharField(choices=STATUS_CHOICES,max_length=20, default = "pending")
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE)
    error = models.TextField(blank=True)
    source_type = models.CharField(choices=SOURCE_CHOICES, max_length=20, default="text")
    total_chunks = models.IntegerField(default=0)
    workflow_run_id = models.CharField(max_length=64, blank=True)




    UNPROCESSED_STATUSES = ("pending", "error")
    RUNNING_STATUSES = ("queued", "scheduled", "processing", "extracting", "embedding")

    @property
    def source_label(self):
        return os.path.basename(self.file.name) if self.file else self.url

    @property
    def is_unprocessed(self):
        return self.status in self.UNPROCESSED_STATUSES

    @property
    def is_running(self):
        return self.status in self.RUNNING_STATUSES

    def __str__(self):

        return self.url or self.file.name



class Chunk(BaseModel):
    embedding = VectorField(dimensions=768)
    chunk_num = models.IntegerField()
    parent_doc = models.ForeignKey(Document, related_name="chunks", on_delete=models.CASCADE)
    content = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parent_doc", "chunk_num"], name="unique_chunk_per_doc"),
        ]
