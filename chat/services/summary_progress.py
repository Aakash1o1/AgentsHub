from chat.temporal_workflow.temporal import ChatFileSummaries
from chat.temporal_workflow.workflows import ChatFileSummaryWorkflow
from scraper.services.progress import DocumentProgress


class ChatFileSummaryProgress:
    STEPS = (
        ("read_text", "Read text"),
        ("summarize_piece", "Summarise pieces"),
        ("combine", "Combine"),
        ("save_summary", "Save summary"),
        ("post_summary", "Post in chat"),
    )

    @classmethod
    def for_message(cls, message, run_id):
        return cls(ChatFileSummaries.workflow_id(message), run_id)

    def __init__(self, workflow_id, run_id):
        self.workflow_id = workflow_id
        self.run_id = run_id
        self.steps = {key: {"key": key, "label": label, "state": "pending"} for key, label in self.STEPS}
        self.steps["summarize_piece"].update(done=0, total=None)
        self.keys_by_event = {}
        self.status = "Running"

    def apply(self, event):
        kind = event.WhichOneof("attributes")
        attrs = getattr(event, kind)
        at = DocumentProgress.moment(event.event_time)
        pieces = self.steps["summarize_piece"]

        if kind in DocumentProgress.CLOSED:
            self.status = DocumentProgress.CLOSED[kind]
        elif kind == "activity_task_scheduled_event_attributes":
            key = attrs.activity_type.name
            self.keys_by_event[event.event_id] = key
            self.steps[key].setdefault("started_at", at)
            self.steps[key]["state"] = "running"
        elif kind == "activity_task_completed_event_attributes":
            key = self.keys_by_event[attrs.scheduled_event_id]
            step = self.steps[key]
            if key == "read_text":
                plan = DocumentProgress.decode(attrs.result.payloads) or {}
                pieces["total"] = plan.get("pieces", 0)
            if key == "summarize_piece":
                pieces["done"] += 1
                if pieces["done"] == pieces["total"]:
                    step.update(state="done", ended_at=at)
            else:
                step.update(state="done", ended_at=at)
        elif kind in ("activity_task_failed_event_attributes", "activity_task_timed_out_event_attributes"):
            step = self.steps[self.keys_by_event[attrs.scheduled_event_id]]
            step.update(state="failed", ended_at=at, last_error=attrs.failure.message)

    def snapshot(self):
        pieces = self.steps["summarize_piece"]
        pieces["progress"] = f"{pieces['done']}/{pieces['total']}" if pieces["total"] is not None else ""
        steps = [dict(step) for step in self.steps.values()]
        if self.status != "Running":
            for step in steps:
                if step["state"] == "running":
                    step["state"] = "stopped"
        return {
            "status": self.status,
            "parallel": ChatFileSummaryWorkflow.PARALLEL,
            "steps_done": sum(step["state"] == "done" for step in steps),
            "steps_total": len(steps),
            "steps": steps,
        }

    async def stream(self):
        last = None
        async for events in ChatFileSummaries.watch(self.workflow_id, self.run_id):
            for event in events:
                self.apply(event)
            snapshot = self.snapshot()
            if snapshot != last:
                last = snapshot
                yield snapshot
            if self.status != "Running":
                return
