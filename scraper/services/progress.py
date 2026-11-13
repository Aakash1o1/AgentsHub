import json
import math
from datetime import timezone

from django.urls import reverse

from scraper.temporal_workflow.temporal import DocumentWorkflows
from scraper.temporal_workflow.workflows import DocumentWorkflow


class DocumentProgress:
    STEPS = (
        ("mark_extracting", "Mark extracting"),
        ("extract_text", "Extract text"),
        ("mark_embedding", "Mark embedding"),
        ("embed_batch", "Embed batches"),
        ("finish", "Finish"),
        ("announce", "Announce"),
    )
    CLOSED = {
        "workflow_execution_completed_event_attributes": "Completed",
        "workflow_execution_failed_event_attributes": "Failed",
        "workflow_execution_terminated_event_attributes": "Terminated",
        "workflow_execution_canceled_event_attributes": "Canceled",
        "workflow_execution_timed_out_event_attributes": "Timed out",
        "workflow_execution_continued_as_new_event_attributes": "Continued as new",
    }
    PAUSE_EVENTS = {
        "workflow_execution_paused_event_attributes": True,
        "workflow_execution_unpaused_event_attributes": False,
    }

    @staticmethod
    def socket_path(doc_id):
        return f"/ws/scraper/document/{doc_id}/progress/"

    @staticmethod
    def decode(payloads, index=0):
        if len(payloads) <= index or not payloads[index].data:
            return None
        return json.loads(payloads[index].data)

    @staticmethod
    def control_url(workflow_id, run_id):
        return reverse("workflow_control", args=[workflow_id, run_id])

    @staticmethod
    def moment(timestamp):
        return timestamp.ToDatetime(tzinfo=timezone.utc).isoformat()

    @classmethod
    def for_document(cls, doc):
        document = {"source": doc.source_label, "type": doc.get_source_type_display()}
        return cls(DocumentWorkflows.workflow_id(doc), doc.workflow_run_id, document)

    @classmethod
    def for_workflow(cls, workflow_id, run_id):
        document = {"source": f"doc {DocumentWorkflows.doc_id(workflow_id)}", "type": workflow_id}
        return cls(workflow_id, run_id, document)

    def __init__(self, workflow_id, run_id, document):
        self.workflow_id = workflow_id
        self.run_id = run_id
        self.document = document
        self.steps = {key: {"key": key, "label": label, "state": "pending"} for key, label in self.STEPS}
        self.steps["embed_batch"].update(done=0, total=None)
        self.keys_by_event = {}
        self.status = "Running"
        self.paused = False

    def activity_key(self, attrs):
        name = attrs.activity_type.name
        if name == "mark_stage":
            return f"mark_{self.decode(attrs.input.payloads, 1)}"
        return name

    def apply(self, event):
        kind = event.WhichOneof("attributes")
        attrs = getattr(event, kind)
        at = self.moment(event.event_time)
        batch = self.steps["embed_batch"]

        if kind in self.CLOSED:
            self.status = self.CLOSED[kind]
        elif kind in self.PAUSE_EVENTS:
            self.paused = self.PAUSE_EVENTS[kind]
        elif kind == "activity_task_scheduled_event_attributes":
            key = self.activity_key(attrs)
            if key not in self.steps:
                return
            self.keys_by_event[event.event_id] = key
            self.steps[key].setdefault("started_at", at)
            self.steps[key]["state"] = "running"
        elif kind == "activity_task_completed_event_attributes":
            key = self.keys_by_event.get(attrs.scheduled_event_id)
            if key is None:
                return
            self.steps[key].update(state="done", ended_at=at)
            if key == "extract_text":
                batch["total"] = math.ceil((self.decode(attrs.result.payloads) or 0) / DocumentWorkflow.BATCH_SIZE)
            if key == "embed_batch":
                batch["done"] += 1
                batch["state"] = "done" if batch["done"] == batch["total"] else "running"
        elif kind in ("activity_task_failed_event_attributes", "activity_task_timed_out_event_attributes"):
            key = self.keys_by_event.get(attrs.scheduled_event_id)
            if key is not None:
                self.steps[key].update(state="failed", ended_at=at, last_error=attrs.failure.message)

    def snapshot(self):
        batch = self.steps["embed_batch"]
        if batch["total"] == 0 and self.steps["finish"]["state"] != "pending":
            batch["state"] = "done"
        batch["progress"] = f"{batch['done']}/{batch['total']}" if batch["total"] is not None else ""

        steps = [dict(step) for step in self.steps.values()]
        if self.status != "Running":
            for step in steps:
                if step["state"] == "running":
                    step["state"] = "stopped"
        return {
            "document": self.document,
            "status": self.status,
            "paused": self.paused and self.status == "Running",
            "control_url": self.control_url(self.workflow_id, self.run_id),
            "steps_done": sum(step["state"] == "done" for step in steps),
            "steps_total": len(steps),
            "steps": steps,
        }

    async def stream(self):
        last = None
        async for events in DocumentWorkflows.watch(self.workflow_id, self.run_id):
            for event in events:
                self.apply(event)
            snapshot = self.snapshot()
            if snapshot != last:
                last = snapshot
                yield snapshot
            if self.status != "Running":
                return
