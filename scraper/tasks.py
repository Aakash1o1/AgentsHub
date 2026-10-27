from celery import shared_task
from django.conf import settings

from scraper.models import Document
from scraper.services.ingestion import ScraperService


class DocumentTasks:
    @shared_task(name="scraper.embed_document")
    def embed_document(document_id):
        doc = Document.objects.filter(id=document_id).first()
        if doc is None:
            return
        ScraperService().vectorize(doc.as_message())

    @classmethod
    def schedule(cls, doc, delay_seconds=None, user=None):
        if delay_seconds is None:
            delay_seconds = settings.DOCUMENT_SCHEDULE_DELAY_SECONDS

        cls.embed_document.apply_async(args=[doc.id], countdown=delay_seconds)

        doc.status = "scheduled"
        doc.workflow_run_id = ""
        fields = ["status", "workflow_run_id", "updated_at"]
        if user is not None:
            doc.updated_by = user
            fields.append("updated_by")
        doc.save(update_fields=fields)
        return delay_seconds
