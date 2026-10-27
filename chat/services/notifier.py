from base.services.broadcast import Broadcaster


class ChatNotifier(Broadcaster):
    EVENT_TYPE = "chat.event"

    # Makes group name for websocket
    @staticmethod
    def chat_group_name(chat_id):
        return f"chat_{chat_id}"

    @staticmethod
    def vendor_group_name(vendor_id):
        return f"vendor_{vendor_id}"

    @classmethod
    def notify_chat(cls, chat_id, payload):
        if not chat_id:
            return
        cls.publish(cls.chat_group_name(chat_id), payload)

    @classmethod
    def notify_vendor(cls, vendor_id, payload):
        if not vendor_id:
            return
        cls.publish(cls.vendor_group_name(vendor_id), payload)

    @classmethod
    def document_finished(cls, vendor_id, document_id, status, error=""):
        if status == "completed":
            detail = f"Document {document_id} has been added to context"
        elif status == "error":
            detail = f"Document {document_id} could not be added to context: {error}"
        else:
            return
        cls.notify_vendor(vendor_id, {"event": "notice", "detail": detail})
