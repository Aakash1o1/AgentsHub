import json

from django.contrib import admin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.text import slugify
from django.views import View

from agent.models import Agent
from agent.services.tools import TOOL_REGISTRY


def _agent_dict(a):
    # Shape one Agent row for the canvas front-end.
    return {
        "id": a.id,
        "slug": a.slug,
        "label": a.label,
        "description": a.description,
        "prompt_name": a.prompt_name,
        "tools": a.tools,
        "is_default": a.is_default,
        "graph_json": a.graph_json,
    }


class AgentGraphView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        vendor = user.active_vendor
        agents = [_agent_dict(a) for a in vendor.agents.all()] if vendor else []

        context = admin.site.each_context(request)
        context.update({
            "is_fullwidth": "1",
            "vendor": vendor,
            # embedded as JSON for the canvas to read (see json_script in template)
            "agents_json": agents,
            # name + docstring + the arguments the LLM must supply (config is injected,
            # so it never appears in .args)
            "available_tools": [
                {"name": name, "description": t.description, "args": list(t.args)}
                for name, t in TOOL_REGISTRY.items()
            ],
        })
        return render(request, "agent_graph.html", context)


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

        # Keep only registry-valid tools, de-duplicated, preserving order.
        tools = list(dict.fromkeys(
            t for t in data.get("tools", []) if t in TOOL_REGISTRY
        ))

        agent_id = data.get("id")

        # slug is unique per vendor -- suffix if the base slug is already taken
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
            "prompt_name": data.get("prompt_name", "").strip(),
            "tools": tools,
            "is_default": bool(data.get("is_default", False)),
            "graph_json": data.get("graph_json", {}),
            "updated_by": user,
        }

        if agent_id:
            # update -- scoped to this vendor so you can't edit someone else's agent
            agent = vendor.agents.filter(id=agent_id).first()
            if not agent:
                return JsonResponse({"ok": False, "error": "Agent not found."}, status=404)
            for k, v in fields.items():
                setattr(agent, k, v)
            agent.save()
        else:
            agent = Agent.objects.create(vendor=vendor, created_by=user, **fields)

        return JsonResponse({"ok": True, "agent": _agent_dict(agent)})
