from django.utils import timezone

from base.services.temporal import TemporalClient
from scraper.models import Document
from scraper.temporal_workflow.workflows import DocumentWorkflow


class DocumentWorkflows(TemporalClient):
    STARTABLE_STATUSES = Document.UNPROCESSED_STATUSES

    @staticmethod
    def workflow_id(doc):
        return f"document-{doc.id}"

    @classmethod
    def start(cls, doc, delay_seconds=0, user=None):
        workflow_id = cls.workflow_id(doc)
        run_id = cls.send(DocumentWorkflow.run, [doc.id, delay_seconds], workflow_id)
        Document.objects.filter(id=doc.id).update(workflow_run_id=run_id)

        fields = {"status": "waiting" if delay_seconds else "queued", "updated_at": timezone.now()}
        if user is not None:
            fields["updated_by"] = user
        Document.objects.filter(id=doc.id, status__in=cls.STARTABLE_STATUSES).update(**fields)
        return workflow_id

    @classmethod
    def stop(cls, doc):
        cls.cancel(cls.workflow_id(doc), doc.workflow_run_id)
