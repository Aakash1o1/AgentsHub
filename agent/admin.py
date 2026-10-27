from django.contrib import admin
from base.admin import VendorScopedAdmin
from .models import Agent


# Register your models here.
@admin.register(Agent)
class AgentAdmin(VendorScopedAdmin):
    vendor_lookup = "vendor"
    list_display = ("label", "slug", "vendor", "is_default", "is_active")
    search_fields = ("label", "slug")
    readonly_on_change = VendorScopedAdmin.readonly_on_change + ("slug", "graph_json")

    fieldsets = (
        (None, {"fields": ("vendor", "label", "slug", "description", "is_default")}),
        ("Behaviour", {"fields": ("prompt_name", "tools", "graph_json")}),
        VendorScopedAdmin.META_FIELDSET,
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # THis fn determines what field widget is used for UI display
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name in ("tools", "graph_json"):
            field.widget.attrs["rows"] = 3
        return field
