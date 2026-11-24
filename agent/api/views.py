import json

from django.contrib import admin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.text import slugify
from django.views import View

from agent.models import Agent
from agent.services.client import AgentClient
from agent.services.tools import TOOL_REGISTRY
from agent.services.workflow import AgentWorkflow
from chat.models import Chat
from chat.services.chat import ChatService
from chat.services.files import ChatFileService


class AgentPayload:
    @staticmethod
    def build(agent):
        return {
            "id": agent.id,
            "slug": agent.slug,
            "label": agent.label,
            "description": agent.description,
            "is_default": agent.is_default,
            "is_active": agent.is_active,
            "workflow_json": agent.workflow_json,
        }


class AgentMessageView(LoginRequiredMixin, View):
    @staticmethod
    def error(text, status):
        return JsonResponse({"detail": text}, status=status)

    def post(self, request, slug):
        user = request.user
        vendor = user.active_vendor
        if vendor is None:
            return self.error("Pick a vendor first.", 404)
        agent = vendor.agents.filter(slug=slug, is_active=True).first()
        if agent is None:
            return self.error(f"No agent '{slug}' for {vendor}.", 404)
        chat = Chat.objects.visible_to(user).filter(id=request.POST.get("chat_id")).first()
        if chat is None:
            return self.error("This chat is no longer available.", 404)
        question = (request.POST.get("question") or "").strip()
        if not question:
            return self.error("Type a question first.", 400)
        token = request.POST.get("file") or ""
        file_url = ChatFileService.url_from_token(token, chat, user) if token else ""
        if token and not file_url:
            return self.error("The attached file could not be used. Upload it again.", 400)
        if not ChatService().ask(chat, agent, question, user, file_url):
            return self.error("Wait for the current answer to finish.", 409)
        return JsonResponse({"agent": agent.slug, "chat_id": chat.id}, status=202)


class AgentGraphView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        vendor = user.active_vendor
        agents = []
        if vendor:
            rows = vendor.agents.order_by("id")
            agents = [AgentPayload.build(agent) for agent in rows]

        context = admin.site.each_context(request)
        context.update({
            "is_fullwidth": "1",
            "vendor": vendor,
            "agents_json": agents,
            "available_tools": [
                {"name": name, "description": t.description, "args": list(t.args)}
                for name, t in TOOL_REGISTRY.items()
            ],
        })
        return render(request, "agent_graph.html", context)


class AgentPromptsView(LoginRequiredMixin, View):
    def get(self, request):
        try:
            names = AgentClient().list_prompts()
        except Exception:
            names = []
        return JsonResponse({"prompts": names})


class AgentGraphSaveView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        vendor = user.active_vendor
        if not vendor:
            return JsonResponse({"ok": False, "error": "No active vendor."}, status=400)

        data = json.loads(request.body)
        label = (data.get("label") or "").strip()
        if not label:
            return JsonResponse({"ok": False, "error": "Agent needs a name."}, status=400)

        workflow = AgentWorkflow(data.get("workflow_json"))
        error = workflow.error(TOOL_REGISTRY)
        if error:
            return JsonResponse({"ok": False, "error": error}, status=400)

        agent_id = data.get("id")

        base = slugify(label) or "agent"
        slug = base
        taken = vendor.agents.exclude(id=agent_id or 0).values_list("slug", flat=True)
        n = 2
        while slug in taken:
            slug = f"{base}-{n}"
            n += 1

        fields = {
            "label": label,
            "slug": slug,
            "description": data.get("description", ""),
            "is_default": bool(data.get("is_default", False)),
            "workflow_json": workflow.clean(),
            "updated_by": user,
        }
        if "is_active" in data:
            fields["is_active"] = bool(data["is_active"])

        with transaction.atomic():
            if agent_id:
                agent = vendor.agents.filter(id=agent_id).first()
                if not agent:
                    return JsonResponse({"ok": False, "error": "Agent not found."}, status=404)
                for k, v in fields.items():
                    setattr(agent, k, v)
                agent.save()
            else:
                agent = Agent.objects.create(vendor=vendor, created_by=user, **fields)

            if agent.is_default:
                vendor.agents.exclude(id=agent.id).filter(is_default=True).update(is_default=False, updated_by=user)

        return JsonResponse({"ok": True, "agent": AgentPayload.build(agent)})
