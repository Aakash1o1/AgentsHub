from django.contrib import admin
from base.admin import VendorScopedAdmin, SoftDeleteAdminMixin
from base.html import AdminHtml
from .models import Agent


# Register your models here.
@admin.register(Agent)
class AgentAdmin(SoftDeleteAdminMixin, VendorScopedAdmin):
    vendor_lookup = "vendor"
    list_display = ("label", "slug", "is_default", "prompt_name")
    search_fields = ("label", "slug", "description", "prompt_name")
    readonly_fields = ("label", "slug", "description", "is_default", "prompt_name", "tool_list")

    fieldsets = (
        (None, {"fields": (("label", "slug"), "description")}),
        ("Details", {
            "fields": ("prompt_name", ("tool_list", "is_default")),
            "classes": ("agent-details",),
        }),
        VendorScopedAdmin.META_FIELDSET,
    )

    class Media:
        css = {"all": ("agent/agent_admin.css",)}

    def has_add_permission(self, request):
        return False

    @admin.display(description="Tools")
    def tool_list(self, obj):
        return AdminHtml.chip_list(obj.tools)
