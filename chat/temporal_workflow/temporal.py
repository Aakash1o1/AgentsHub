from base.services.temporal import TemporalClient
from chat.temporal_workflow.workflows import ChatFileSummaryWorkflow


class ChatFileSummaries(TemporalClient):
    WORKFLOW_TYPE = ChatFileSummaryWorkflow.__name__
    WORKFLOW_PREFIX = "chat-file-summary-"

    @classmethod
    def workflow_id(cls, message):
        return f"{cls.WORKFLOW_PREFIX}{message.id}"

    @classmethod
    def message_id(cls, workflow_id):
        return int(workflow_id.removeprefix(cls.WORKFLOW_PREFIX))

    @classmethod
    def job_label(cls, workflow_id):
        return f"summary of file {cls.message_id(workflow_id)}"

    @staticmethod
    def job_socket_path(workflow_id, run_id):
        return f"/ws/chat/workflow/{workflow_id}/{run_id}/summary/"

    @staticmethod
    def socket_path(message, run_id):
        return f"/ws/chat/file/{message.id}/summary/{run_id}/"

    @classmethod
    def start(cls, message):
        return cls.send(ChatFileSummaryWorkflow.run, [message.id], cls.workflow_id(message))
