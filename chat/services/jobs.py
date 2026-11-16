from django.urls import reverse
from base.services.temporal import JobLabels, TemporalClient, WorkflowRun
from chat.models import Chat
from chat.services.files import ChatFileService
from chat.temporal_workflow.temporal import ChatFileSummaries
from scraper.services.progress import DocumentProgress
from scraper.temporal_workflow.temporal import DocumentWorkflows


class ChatJobs:
    TABS = ("running", "failed", "todo", "done")
    RUN_TABS = {WorkflowRun.RUNNING: "running", WorkflowRun.PAUSED: "running", WorkflowRun.COMPLETED: "done"}
    DOC_TABS = {"completed": "done", "error": "failed"}
    IDS_PER_QUERY = 200

    @staticmethod
    def newest(executions):
        runs = {}
        for execution in executions:
            current = runs.get(execution.id)
            if current is None or execution.start_time > current.start_time:
                runs[execution.id] = execution
        return runs

    @classmethod
    def runs_of(cls, workflow_ids, vendor_id, user_id):
        executions = []
        for start in range(0, len(workflow_ids), cls.IDS_PER_QUERY):
            ids = ", ".join(f"'{workflow_id}'" for workflow_id in workflow_ids[start:start + cls.IDS_PER_QUERY])
            executions += TemporalClient.list(f"WorkflowId IN ({ids}) AND {JobLabels.vendor_query(vendor_id)} AND {JobLabels.user_query(user_id)}")
        return cls.newest(executions)

    @classmethod
    def tasks(cls, user, chat=None):
        if user.active_vendor is None:
            return []
        files = [message for message in ChatFileService.for_chats(Chat.objects.visible_to(user)) if not message.is_dataset]
        workflow_ids = [ChatFileSummaries.workflow_id(message) for message in files]
        workflow_ids += [DocumentWorkflows.workflow_id(message.document) for message in files if message.document_id]
        runs = cls.runs_of(workflow_ids, user.active_vendor.id, user.id)
        rows = []
        for message in files:
            rows.append(cls.summary_task(message, runs.get(ChatFileSummaries.workflow_id(message))))
            kb_run = runs.get(DocumentWorkflows.workflow_id(message.document)) if message.document_id else None
            rows.append(cls.kb_task(message, kb_run))
        return [row for row in rows if row["tab"] != "todo" or (chat is not None and row["chat_id"] == chat.id)]

    @classmethod
    def task(cls, message, job, execution, **fields):
        row = {"key": f"{job}-{message.id}", "file_id": message.id, "name": message.file_label, "job": job,
               "chat_id": message.chat_id, "chat": message.chat.title,
               "tab": "todo", "reason": "", "finished_at": None, **fields}
        if execution is not None:
            row["tab"] = cls.RUN_TABS.get(execution.status, "failed")
            row["finished_at"] = execution.close_time.isoformat() if execution.close_time else None
            if row["tab"] == "failed":
                row["reason"] = execution.status_name.replace("_", " ")
        return row

    @classmethod
    def summary_task(cls, message, execution):
        row = cls.task(message, "summary", execution, action="summary",
                       action_url=reverse("start_file_summary", args=[message.id]))
        if execution is not None:
            row["progress_url"] = ChatFileSummaries.socket_path(message, execution.run_id)
        return row

    @classmethod
    def kb_task(cls, message, execution):
        if not message.document_id:
            return cls.task(message, "kb", None, action="add",
                            action_url=reverse("add_file_to_knowledge", args=[message.id]))
        row = cls.task(message, "kb", execution, action="start",
                       action_url=reverse("enqueue_document", args=[message.document_id]),
                       progress_url=DocumentProgress.socket_path(message.document_id))
        if execution is None:
            row["tab"] = cls.DOC_TABS.get(message.document.status, "todo")
        return row
