import json

from django.contrib import admin
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html
from django.utils.text import Truncator
from .models import Document, Chunk
from base.html import AdminHtml
from base.admin import VendorScopedAdmin, SoftDeleteAdminMixin
from scraper.services.progress import DocumentProgress
from scraper.services.queue import DocumentQueue
from scraper.tasks import DocumentTasks



STATUS_COLORS = {"pending": "gray", "queued": "blue", "scheduled": "purple",
                 "processing": "orange", "waiting": "purple", "extracting": "orange",
                 "embedding": "orange", "completed": "green", "error": "red"}
# Register your models here.

@admin.register(Document)
class DocumentAdmin(SoftDeleteAdminMixin, VendorScopedAdmin):
    list_display = ("id", "vendor", "source_type", "colored_status", "chunk_count", "run_id", "action", "created_by", "created_at")
    list_select_related = ("vendor", "created_by") #Basically it tells django to fetch the vendor and created by FK values when the table row is fetched
    search_fields = ("url","status")

    readonly_fields = ("chunk_count", "status", "error", "workflow_run_id")
    readonly_on_change = VendorScopedAdmin.readonly_on_change + ("vendor", "source_type")

    def has_add_permission(self, request):
        return request.user.active_vendor is not None and super().has_add_permission(request)

    def auto_fill_values(self, request):
        return {**super().auto_fill_values(request), "vendor": request.user.active_vendor}

    ACTION_MODES = [
        {"mode": "process", "label": "Process", "group": "Kafka & Celery",
         "hint": "Kafka queue -- runs when the consumer reaches it", "colour": "#2563eb"},
        {"mode": "process_now", "label": "Process now", "group": "Kafka & Celery",
         "hint": "Priority queue -- next after the current document", "colour": "#7c3aed"},
        {"mode": "schedule", "label": "Schedule 2 min", "group": "Kafka & Celery",
         "hint": "Celery -- embedded after a delay", "colour": "#0f766e"},
        {"mode": "process_temporal", "label": "Process", "group": "Temporal",
         "hint": "Temporal workflow -- resumes after a crash, saves per batch", "colour": "#db2777"},
        {"mode": "schedule_temporal", "label": "Schedule 2 min", "group": "Temporal",
         "hint": "Temporal timer -- the wait is stored on the Temporal server", "colour": "#b45309"},
    ]


    fieldsets = (
        (None, {"fields": (("vendor", "url"), ("file", "source_type"),
                           ("status", "chunk_count"), "workflow_run_id", "error")}),
        VendorScopedAdmin.META_FIELDSET,
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_chunk_count=Count("chunks"))

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # THis fn determines what field widget is used for UI display
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "error":
            field.widget.attrs["rows"] = 2
        return field

    @admin.display(description="Run ID", ordering="workflow_run_id")
    def run_id(self, obj):
        if not obj.workflow_run_id:
            return "-"
        return format_html('<span title="{}" style="font-family:monospace;">{}…</span>', obj.workflow_run_id, obj.workflow_run_id[:8])

    @admin.display(description="Chunks", ordering="_chunk_count")
    def chunk_count(self, obj):
        return getattr(obj, "_chunk_count", None) or obj.chunks.count()

    actions = ["bulk_process", "bulk_process_now", "bulk_schedule"] + SoftDeleteAdminMixin.SOFT_DELETE_ACTIONS


    class Media:
        css = {"all": ("scraper/doc_actions.css",)}
        js = (
            "https://cdn.jsdelivr.net/npm/sweetalert2@11.14.5/dist/sweetalert2.all.min.js",
            "scraper/doc_actions.js",
        )

    @admin.display(description="Action")
    def action(self, obj):
        progress_url = DocumentProgress.socket_path(obj.id) if obj.workflow_run_id else ""
        cancel_url = reverse("cancel_document", args=[obj.id])
        if obj.is_unprocessed:
            return AdminHtml.js_action_button(
                "Actions",
                "doc-action-btn",
                doc=obj.id,
                url=reverse("enqueue_document", args=[obj.id]),
                modes=json.dumps(self.ACTION_MODES),
                progress_url=progress_url,
                cancel_url=cancel_url,
            )
        if progress_url:
            return AdminHtml.js_action_button("Progress", "doc-progress-btn", doc=obj.id, url=progress_url, cancel_url=cancel_url)
        return ""

    def enqueue_selected(self, request, queryset, mode):
        done, failed = 0, 0
        for doc in queryset:
            try:
                if mode == "schedule":
                    DocumentTasks.schedule(doc, user=request.user)
                else:
                    DocumentQueue.publish(doc, priority=(mode == "process_now"), user=request.user)
                done += 1
            except Exception:
                failed += 1
        self.message_user(request, f"{done} queued, {failed} failed.")

    @admin.action(description="Process (Kafka queue)")
    def bulk_process(self, request, queryset):
        self.enqueue_selected(request, queryset, "process")

    @admin.action(description="Process now (priority)")
    def bulk_process_now(self, request, queryset):
        self.enqueue_selected(request, queryset, "process_now")

    @admin.action(description="Schedule in 2 minutes (Celery)")
    def bulk_schedule(self, request, queryset):
        self.enqueue_selected(request, queryset, "schedule")


    @admin.display(description="Status")
    def colored_status(self,obj):
        color = STATUS_COLORS.get(obj.status,"black")
        return AdminHtml.colored_badge(obj.get_status_display(), color)


    @admin.display(description="Document")
    def doc_link(self, obj):
        return AdminHtml.change_link(obj)



@admin.register(Chunk)
class ChunkAdmin(VendorScopedAdmin):
    vendor_lookup = "parent_doc__vendor"    # Chunk has no direct vendor FK
    list_display = ("short_content", "parent_doc_id", "chunk_num", "created_at")
    list_filter = ("parent_doc__source_type",)
    search_fields = ("content", "parent_doc__url")

    readonly_fields = ("parent_doc", "embedding_info", "created_at", "updated_at", "created_by", "updated_by")
    readonly_on_change = VendorScopedAdmin.readonly_on_change + ("content", "chunk_num")

    def has_add_permission(self, request):
        return False

    fieldsets = (
        ("Chunk", {
            "fields": (("parent_doc", "chunk_num"), "content"),
        }),
        ("Vector", {
            "fields": ("embedding_info",),
        }),
        VendorScopedAdmin.META_FIELDSET,
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # This fn determines what field widget is used for UI display
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "content":
            field.widget.attrs["rows"] = 4
        return field

    @admin.display(description="Content")
    def short_content(self, obj):
        return Truncator(obj.content).chars(120)

    @admin.display(description="Embedding")
    def embedding_info(self, obj):
        return f"{len(obj.embedding)} dimensions" if obj.embedding is not None else ""
