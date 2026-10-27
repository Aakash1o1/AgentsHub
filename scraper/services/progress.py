import json
import math
from datetime import timezone

from scraper.temporal_workflow.temporal import DocumentWorkflows
from scraper.temporal_workflow.workflows import DocumentWorkflow


class DocumentProgress:
    STEPS = (
        ("mark_waiting", "Mark waiting"),
        ("timer", "Timer"),
        ("mark_extracting", "Mark extracting"),
        ("extract_text", "Extract text"),
        ("mark_embedding", "Mark embedding"),
        ("embed_batch", "Embed batches"),
        ("finish", "Finish"),
        ("announce", "Announce"),
    )
    DELAY_ONLY = ("mark_waiting", "timer")
    CLOSED = {
        "workflow_execution_completed_event_attributes": "Completed",
        "workflow_execution_failed_event_attributes": "Failed",
        "workflow_execution_terminated_event_attributes": "Terminated",
        "workflow_execution_canceled_event_attributes": "Canceled",
        "workflow_execution_timed_out_event_attributes": "Timed out",
        "workflow_execution_continued_as_new_event_attributes": "Continued as new",
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
    def moment(timestamp):
        return timestamp.ToDatetime(tzinfo=timezone.utc).isoformat()

    def __init__(self, doc):
        self.doc = doc
        self.document = {
            "source": doc.source_label,
            "type": doc.get_source_type_display(),
        }
        self.steps = {key: {"key": key, "label": label, "state": "pending"} for key, label in self.STEPS}
        self.steps["embed_batch"].update(done=0, total=None)
        self.keys_by_event = {}
        self.delayed = False
        self.status = "Running"

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

        if kind == "workflow_execution_started_event_attributes":
            self.delayed = bool(self.decode(attrs.input.payloads, 1))
        elif kind in self.CLOSED:
            self.status = self.CLOSED[kind]
        elif kind == "activity_task_scheduled_event_attributes":
            key = self.activity_key(attrs)
            self.keys_by_event[event.event_id] = key
            self.steps[key].setdefault("started_at", at)
            self.steps[key]["state"] = "running"
        elif kind == "activity_task_completed_event_attributes":
            key = self.keys_by_event[attrs.scheduled_event_id]
            self.steps[key].update(state="done", ended_at=at)
            if key == "extract_text":
                batch["total"] = math.ceil((self.decode(attrs.result.payloads) or 0) / DocumentWorkflow.BATCH_SIZE)
            if key == "embed_batch":
                batch["done"] += 1
                batch["state"] = "done" if batch["done"] == batch["total"] else "running"
        elif kind in ("activity_task_failed_event_attributes", "activity_task_timed_out_event_attributes"):
            step = self.steps[self.keys_by_event[attrs.scheduled_event_id]]
            step.update(state="failed", ended_at=at, last_error=attrs.failure.message)
        elif kind == "timer_started_event_attributes":
            fires_at = event.event_time.ToDatetime(tzinfo=timezone.utc) + attrs.start_to_fire_timeout.ToTimedelta()
            self.steps["timer"].update(state="running", started_at=at, fires_at=fires_at.isoformat())
        elif kind == "timer_fired_event_attributes":
            self.steps["timer"].update(state="done", ended_at=at)

    def snapshot(self):
        batch = self.steps["embed_batch"]
        if batch["total"] == 0 and self.steps["finish"]["state"] != "pending":
            batch["state"] = "done"
        batch["progress"] = f"{batch['done']}/{batch['total']}" if batch["total"] is not None else ""

        steps = [dict(step) for key, step in self.steps.items() if self.delayed or key not in self.DELAY_ONLY]
        if self.status != "Running":
            for step in steps:
                if step["state"] == "running":
                    step["state"] = "stopped"
        return {
            "document": self.document,
            "status": self.status,
            "steps_done": sum(step["state"] == "done" for step in steps),
            "steps_total": len(steps),
            "steps": steps,
        }

    async def stream(self):
        last = None
        async for events in DocumentWorkflows.watch(DocumentWorkflows.workflow_id(self.doc), self.doc.workflow_run_id):
            for event in events:
                self.apply(event)
            snapshot = self.snapshot()
            if snapshot != last:
                last = snapshot
                yield snapshot
            if self.status != "Running":
                return
