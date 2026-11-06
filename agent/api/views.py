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


class AgentPayload:
    @staticmethod
    def build(agent):
        return {
            "id": agent.id,
            "slug": agent.slug,
            "label": agent.label,
            "description": agent.description,
            "prompt_name": agent.prompt_name,
            "tools": agent.tools,
            "is_default": agent.is_default,
            "is_active": agent.is_active,
            "graph_json": agent.graph_json,
        }


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

        prompt_name = (data.get("prompt_name") or "").strip()
        if not prompt_name:
            return JsonResponse({"ok": False, "error": "Agent needs a prompt name."}, status=400)

        tools = list(dict.fromkeys(
            t for t in data.get("tools", []) if t in TOOL_REGISTRY
        ))

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
            "prompt_name": prompt_name,
            "tools": tools,
            "is_default": bool(data.get("is_default", False)),
            "graph_json": data.get("graph_json", {}),
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
