from celery import shared_task
from django.contrib.auth import get_user_model

from chat.models import Chat
from chat.services.chat import ChatService
from chat.services.notifier import ChatNotifier


class ChatTasks:
    @shared_task(name="chat.answer")
    def answer(chat_id, question, user_id):
        chat = Chat.objects.filter(id=chat_id, is_active=True).first()
        if chat is None:
            ChatService.finish_answering(chat_id)
            return
        user = get_user_model().objects.filter(id=user_id).first()
        service = ChatService()
        try:
            message = service.answer_question(chat, question, user)
        except Exception as error:
            ChatNotifier.notify_chat(chat_id, {"event": "error", "detail": str(error)})
            return
        finally:
            service.finish_answering(chat_id)
        ChatNotifier.notify_chat(chat_id, {"event": "message", "message": service.serialize_message(message)})
