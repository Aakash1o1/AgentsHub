from django.db.models import Q
from django.utils import timezone
from scraper.services.client import DeepseekClient
from chat.models import Chat, Message
from chat.services.notifier import ChatNotifier

class ChatService:
    TITLE_WORDS = 6

    def __init__(self):
        self.deepseek = DeepseekClient()

    @staticmethod
    def fit_title(text):
        title = " ".join((text or "").split())
        max_length = Chat._meta.get_field("title").max_length
        if len(title) > max_length:
            title = title[:max_length - 1].rstrip() + "…"
        return title

    def title_from_question(self, question):
        words = question.split()
        title = " ".join(words[:self.TITLE_WORDS])
        if len(words) > self.TITLE_WORDS:
            title += "…"
        return self.fit_title(title)

    def title_from_first_message(self, chat, question, user):
        title = self.title_from_question(question)
        renamed = Chat.objects.filter(
            id=chat.id, title=Chat.DEFAULT_TITLE, messages__isnull=True
        ).update(title=title, updated_by=user, updated_at=timezone.now())
        if renamed:
            chat.title = title
        return bool(renamed)

    @staticmethod
    def start_answering(chat):
        free = Q(answering_since__isnull=True) | Q(answering_since__lt=Chat.answer_lock_cutoff())
        return bool(Chat.objects.filter(free, id=chat.id).update(answering_since=timezone.now()))

    @staticmethod
    def finish_answering(chat_id):
        Chat.objects.filter(id=chat_id).update(answering_since=None)

    def ask(self, chat, question, user, file_url=""):
        if not self.start_answering(chat):
            return False
        renamed = self.title_from_first_message(chat, question, user)
        user_message = self.save_user_message(chat, question, user, file_url)
        ChatNotifier.notify_chat(chat.id, {"event": "message", "message": self.serialize_message(user_message)})
        if renamed:
            ChatNotifier.notify_chat(chat.id, {"event": "renamed", "chat_id": chat.id, "title": chat.title})
        ChatNotifier.notify_chat(chat.id, {"event": "thinking"})
        self.queue_answer(chat, question, user)
        return True

    def queue_answer(self, chat, question, user):
        from chat.tasks import ChatTasks
        try:
            ChatTasks.answer.delay(chat.id, question, user.id)
        except Exception as error:
            self.finish_answering(chat.id)
            ChatNotifier.notify_chat(chat.id, {"event": "error", "detail": f"Could not queue the answer: {error}"})

    def save_user_message(self, chat, question, user, file_url=""):
        return Message.objects.create(
            chat=chat,
            role="user",
            message=question,
            attachment=file_url,
            chat_session_key=chat.session_key,
            user=user,
            created_by=user,
            updated_by=user,
        )

    def answer_question(self, chat, question, user):
        from agent.services.graph import AgentRunner
        answer, agent, artifact = AgentRunner().run_agent(question, chat.vendor, chat)
        return Message.objects.create(
            chat=chat,
            role="assistant",
            message=Message.join_content(answer, artifact),
            agent=agent,
            chat_session_key=chat.session_key,
            user=user,
            created_by=user,
            updated_by=user,
        )

    def serialize_message(self, message):
        return {
            "id": message.id,
            "role": message.role,
            "message": message.text,
            "agent": message.agent.label if message.agent else "",
            "artifact": message.artifact,
            "attachment": self.serialize_attachment(message),
        }

    @staticmethod
    def serialize_attachment(message):
        if not message.has_source:
            return None
        return {"name": message.file_label, "kind": "link" if message.url else "file"}


    # Function to summarize chat and save it in summary field
    def summarize_chat(self, chat, user):
        message = chat.messages.visible().order_by("created_at")
        convo = "\n".join(f"{m.role}: {m.text}" for m in message)
        prompt = f"Summarize this conversation briefly:\n\n{convo}"
        summary = self.deepseek.ask_deepseek(prompt)
        chat.summary = summary
        chat.updated_by = user
        chat.save()
        # The caller decides how to show this -- the agent turn already stores
        # its own answer, so writing a Message here duplicated it.
        return summary


