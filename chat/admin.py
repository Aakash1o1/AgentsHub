import json

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.text import Truncator
from .models import Chat, Message
from base.admin import VendorScopedAdmin, SoftDeleteAdminMixin, ActiveListFilter
from base.html import AdminHtml
from unfold.admin import TabularInline


class MessageInline(TabularInline):
    model = Message
    fields = ("user_message", "assistant_message")
    readonly_fields = ("user_message", "assistant_message")

    ordering = ("created_at", "id")
    extra = 0
    can_delete = False
    hide_title = True

    EMPTY = mark_safe("<span></span>")

    @admin.display(description="User")
    def user_message(self, obj):
        return obj.text if obj.role == "user" else self.EMPTY

    @admin.display(description="Assistant")
    def assistant_message(self, obj):
        return obj.text if obj.role == "assistant" else self.EMPTY

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).visible()




# Register your models here.
@admin.register(Chat)
class ChatAdmin(SoftDeleteAdminMixin, VendorScopedAdmin):
    vendor_lookup = "vendor"
    list_display = ("user", "session_key", "title", "summary", "created_at")
    list_select_related = ("user",)
    search_fields = ("title",)
    inlines = [MessageInline]

    readonly_fields = ("session_key",)
    readonly_on_change = VendorScopedAdmin.readonly_on_change + ("summary",)

    fieldsets = (
        (None, {"fields": (("user", "vendor"), ("title", "summary"), "session_key")}),
        VendorScopedAdmin.META_FIELDSET,
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # THis fn determines what field widget is used for UI display
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "summary":
            field.widget.attrs["rows"] = 3
        return field





@admin.register(Message)
class MessageAdmin(SoftDeleteAdminMixin, VendorScopedAdmin):
    vendor_lookup = "chat__vendor"    # Message reaches vendor through its chat
    readonly_on_change = VendorScopedAdmin.readonly_on_change + ("chat_session_key", "user", "chat", "role", "agent", "message")
    list_display = ("user", "chat_session_key", "role", "types", "short_message", "created_at")
    list_select_related = ("user",)
    ordering = ("-id",)
    list_filter = (ActiveListFilter, ("attachment", admin.EmptyFieldListFilter))
    search_fields = ("message",)
    readonly_fields = ("types", "attachment_link", "artifact_json")

    fieldsets = (
        (None, {"fields": ("user", ("chat", "chat_session_key"), ("role", "agent"),
                           "message", ("types", "attachment_link"), "artifact_json")}),
        VendorScopedAdmin.META_FIELDSET,
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # THis fn determines what field widget is used for UI display
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "message":
            field.widget.attrs["rows"] = 4
        return field

    def has_add_permission(self, request):
        return False

    @admin.display(description="Types")
    def types(self, obj):
        return ", ".join(obj.message_types) or "-"

    @admin.display(description="Attachment")
    def attachment_link(self, obj):
        if not obj.attachment:
            return "-"
        return AdminHtml.link_button(obj.attachment.url, obj.file_label, icon="download", download=True)

    @admin.display(description="Artifact")
    def artifact_json(self, obj):
        if not obj.artifact:
            return "-"
        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", json.dumps(obj.artifact, indent=2))

    @admin.display(description="Message", ordering="message")
    def short_message(self, obj):
        return Truncator(obj.text).chars(60)

