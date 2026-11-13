from django.contrib import admin
from django.urls import reverse
from base.admin import VendorScopedAdmin, SoftDeleteAdminMixin
from base.html import AdminHtml
from .models import Agent


# Register your models here.
@admin.register(Agent)
class AgentAdmin(SoftDeleteAdminMixin, VendorScopedAdmin):
    vendor_lookup = "vendor"
    list_display = ("label", "slug", "prompt_name", "tool_count", "builder_link")
    search_fields = ("label", "slug", "description")
    ordering = ("label",)
    readonly_fields = ("label", "description", "prompt_name", "workflow")

    fieldsets = (
        (None, {"fields": ("label", "description", "prompt_name", "workflow")}),
        VendorScopedAdmin.META_FIELDSET,
    )

    def has_add_permission(self, request):
        return False

    @admin.display(description="Prompt")
    def prompt_name(self, obj):
        return obj.workflow.prompt_name or "-"

    @admin.display(description="Tools")
    def tool_count(self, obj):
        return len(obj.workflow.tools)

    @admin.display(description="Edit")
    def builder_link(self, obj):
        return AdminHtml.link_button(f"{reverse('agent_graph')}?agent={obj.id}", "Open in Agent Builder", icon="account_tree")

    @admin.display(description="Workflow JSON")
    def workflow(self, obj):
        return AdminHtml.json_block(obj.workflow_json)
