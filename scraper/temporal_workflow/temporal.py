from django.utils import timezone

from base.services.temporal import JobLabels, TemporalClient
from scraper.models import Document
from scraper.temporal_workflow.workflows import DocumentWorkflow


class DocumentWorkflows(TemporalClient):
    STARTABLE_STATUSES = Document.UNPROCESSED_STATUSES
    WORKFLOW_TYPE = DocumentWorkflow.__name__
    WORKFLOW_PREFIX = "document-"
    JOB_KIND = "Knowledge base"

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
        labels, memo = cls.labels(doc)
        run_id = cls.send(DocumentWorkflow.run, [doc.id], workflow_id, labels, memo)
        Document.objects.filter(id=doc.id).update(workflow_run_id=run_id)

        fields = {"status": "queued", "updated_at": timezone.now()}
        if user is not None:
            fields["updated_by"] = user
        Document.objects.filter(id=doc.id, status__in=cls.STARTABLE_STATUSES).update(**fields)
        return workflow_id

    @classmethod
    def paused_doc_ids(cls, docs):
        runs = {cls.workflow_id(doc): doc.workflow_run_id for doc in docs if doc.workflow_run_id}
        if not runs:
            return set()
        ids = ", ".join(f"'{workflow_id}'" for workflow_id in runs)
        paused = cls.list(f"ExecutionStatus = 'Paused' AND WorkflowId IN ({ids})")
        return {cls.doc_id(run.id) for run in paused if runs.get(run.id) == run.run_id}

    @staticmethod
    def labels(doc):
        message = doc.chat_messages.filter(chat__isnull=False).select_related("chat").order_by("id").first()
        if message is None:
            return JobLabels.build(vendor_id=doc.vendor_id, user_id=doc.created_by_id), {"file": doc.source_label}
        return JobLabels.build(chat=message.chat, vendor_id=doc.vendor_id), JobLabels.memo(message)
