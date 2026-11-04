from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer

from chat.services.files import ChatFileService
from chat.models import Chat
from chat.services.chat import ChatService
from chat.services.notifier import ChatNotifier


class ChatSocket(JsonWebsocketConsumer):
    def group_name(self):
        return ChatNotifier.chat_group_name(self.chat_id)

    def vendor_group_name(self):
        return ChatNotifier.vendor_group_name(self.chat.vendor_id)

    def load_chat(self):
        user = self.scope["user"]
        if not user.is_authenticated or not user.active_vendor:
            return None
        return Chat.objects.visible_to(user).filter(id=self.chat_id).first()

    # Auto called when websocket request is received
    def connect(self):
        # Auth before opening a websocket
        self.chat_id = self.scope["url_route"]["kwargs"]["chat_id"]
        self.chat = self.load_chat()
        if self.chat is None:
            self.close()
            return
        async_to_sync(self.channel_layer.group_add)(self.group_name(), self.channel_name)
        async_to_sync(self.channel_layer.group_add)(self.vendor_group_name(), self.channel_name)
        self.accept()

    def disconnect(self, code):
        if getattr(self, "chat", None) is not None:
            async_to_sync(self.channel_layer.group_discard)(self.group_name(), self.channel_name)
            async_to_sync(self.channel_layer.group_discard)(self.vendor_group_name(), self.channel_name)

    def chat_event(self, event):
        self.send_json(event["payload"])


class ChatConsumer(ChatSocket):
    def receive_json(self, content, **kwargs):
        question = (content.get("question") or "").strip()
        if not question:
            return

        if self.load_chat() is None:
            self.send_json({"event": "error", "detail": "This chat is no longer available."})
            return

        service = ChatService()
        user = self.scope["user"]
        token = content.get("file") or ""
        file_path = ChatFileService.path_from_token(token, self.chat, user) if token else ""
        if token and not file_path:
            self.send_json({"event": "error", "detail": "The attached file could not be used. Upload it again."})
            return

        if not service.ask(self.chat, question, user, file_path):
            self.send_json({"event": "busy", "detail": "Wait for the current answer to finish."})
