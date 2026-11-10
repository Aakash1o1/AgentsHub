from django.utils import timezone

from base.services.temporal import TemporalClient
from scraper.models import Document
from scraper.temporal_workflow.workflows import DocumentWorkflow


class DocumentWorkflows(TemporalClient):
    STARTABLE_STATUSES = Document.UNPROCESSED_STATUSES
    WORKFLOW_TYPE = DocumentWorkflow.__name__
    WORKFLOW_PREFIX = "document-"

    @classmethod
    def workflow_id(cls, doc):
        return f"{cls.WORKFLOW_PREFIX}{doc.id}"

    @classmethod
    def doc_id(cls, workflow_id):
        return int(workflow_id.removeprefix(cls.WORKFLOW_PREFIX))

    @classmethod
    def job_label(cls, workflow_id):
        return f"doc {cls.doc_id(workflow_id)}"

    @staticmethod
    def job_socket_path(workflow_id, run_id):
        return f"/ws/scraper/workflow/{workflow_id}/{run_id}/progress/"

    @classmethod
    def start(cls, doc, user=None):
        workflow_id = cls.workflow_id(doc)
        run_id = cls.send(DocumentWorkflow.run, [doc.id], workflow_id)
        Document.objects.filter(id=doc.id).update(workflow_run_id=run_id)

        fields = {"status": "queued", "updated_at": timezone.now()}
        if user is not None:
            fields["updated_by"] = user
        Document.objects.filter(id=doc.id, status__in=cls.STARTABLE_STATUSES).update(**fields)
        return workflow_id

    @classmethod
    def stop(cls, doc):
        cls.cancel(cls.workflow_id(doc), doc.workflow_run_id)
