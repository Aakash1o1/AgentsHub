from celery import shared_task
from django.contrib.auth import get_user_model

from agent.models import Agent
from chat.models import Chat
from chat.services.chat import ChatService
from chat.services.notifier import ChatNotifier


class ChatTasks:
    @shared_task(name="chat.answer")
    def answer(chat_id, agent_id, question, user_id):
        chat = Chat.objects.filter(id=chat_id, is_active=True).first()
        if chat is None:
            ChatService.finish_answering(chat_id)
            return
        agent = Agent.objects.filter(id=agent_id, vendor_id=chat.vendor_id).first()
        if agent is None:
            ChatService.finish_answering(chat_id)
            ChatNotifier.notify_chat(chat_id, {"event": "error", "detail": "This agent is no longer available."})
            return
        user = get_user_model().objects.filter(id=user_id).first()
        service = ChatService()
        try:
            message = service.answer_question(chat, agent, question, user)
        except Exception as error:
            ChatNotifier.notify_chat(chat_id, {"event": "error", "detail": str(error)})
            return
        finally:
            service.finish_answering(chat_id)
        ChatNotifier.notify_chat(chat_id, {"event": "message", "message": service.serialize_message(message)})
