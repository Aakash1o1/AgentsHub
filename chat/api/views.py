from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import JsonResponse
from chat.models import Chat, Message
from scraper.models import Document
from chat.services.chat import ChatService
from chat.services.files import ChatFileService
from chat.services.notifier import ChatNotifier
from django.contrib import admin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View


# Create your views here
class ChatHomeView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        vendor = user.active_vendor
        chats = self.recently_used(Chat.objects.visible_to(user)) if vendor else []
        chat_id = request.GET.get("chat")
        open_chat = None
        if chat_id and vendor:
            open_chat = Chat.objects.visible_to(user).filter(id=chat_id).first()# Without first, it will return a container and for foretign key checks, we need an object
        context = admin.site.each_context(request)
        context.update({
            "is_fullwidth": "1",
            "title": "Chat",
            "user": user,
            "vendors": user.vendors.all(),
            "vendor": user.active_vendor,
            "chats": chats,
            "open_chat": open_chat,
            "chat_messages": open_chat.messages.visible() if open_chat else [],
        })
        return render(request, "chat_admin.html", context)

    @staticmethod
    def recently_used(chats):
        return chats.order_by("-last_message_at", "-id")


class CreateChatView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        if user.active_vendor:
            chat = Chat.objects.create(vendor=user.active_vendor, title=Chat.DEFAULT_TITLE, user=user, created_by=user, updated_by=user)
            return redirect(f"/?chat={chat.id}")
        return redirect("chat_home")


class SendMessageView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        chat_id = request.POST.get("chat_id")
        question = request.POST.get("question")
        chat = Chat.objects.visible_to(user).filter(id=chat_id).first() if user.active_vendor else None
        token = request.POST.get("file") or ""
        file_path = ChatFileService.path_from_token(token, chat, user) if chat and token else ""
        if chat and question:
            ChatService().ask(chat, question, user, file_path)
        if chat:
            return redirect(f"/?chat={chat.id}")
        return redirect("chat_home")

class SummarizeView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        chat_id = request.POST.get("chat_id")
        chat = Chat.objects.visible_to(user).filter(id=chat_id).first() if user.active_vendor else None
        if chat:
            ChatService().summarize_chat(chat, user)
            return redirect(f"/?chat={chat.id}")
        return redirect("chat_home")


class AddChatLinkView(LoginRequiredMixin, View):
    REPLY = "Link saved to this chat. Ask a question about it, or ask me to add it to the knowledge base."

    @staticmethod
    def error(text):
        return JsonResponse({"level": "error", "message": text}, status=400)

    def post(self, request):
        user = request.user
        url = request.POST.get("url", "").strip()
        source_type = request.POST.get("source_type") or ChatFileService.link_type(url)
        chat = Chat.objects.visible_to(user).filter(id=request.POST.get("chat_id") or None).first() if user.active_vendor else None
        if chat is None:
            return self.error("Open a chat first.")
        if source_type not in dict(Document.SOURCE_CHOICES):
            return self.error("Unknown link type.")
        try:
            URLValidator(schemes=["http", "https"])(url)
        except ValidationError:
            return self.error("Enter a full http(s) link.")

        service = ChatService()
        renamed = service.title_from_first_message(chat, url, user)
        link = ChatFileService.save_link(chat, url, source_type, user)
        reply = Message.objects.create(chat=chat, role="assistant", message=self.REPLY,
                                       chat_session_key=chat.session_key, user=user, created_by=user, updated_by=user)
        for message in (link, reply):
            ChatNotifier.notify_chat(chat.id, {"event": "message", "message": service.serialize_message(message)})
        if renamed:
            ChatNotifier.notify_chat(chat.id, {"event": "renamed", "chat_id": chat.id, "title": chat.title})
        return JsonResponse({"level": "success", "id": link.id, "message": self.REPLY})
