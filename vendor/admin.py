from django.contrib import admin
from unfold.admin import ModelAdmin
from base.admin import AuditFieldsAdminMixin
from .models import Vendor

# Register your models here.
@admin.register(Vendor)
class VendorAdmin(AuditFieldsAdminMixin, ModelAdmin):
    list_display = ("name", "slug", "phone", "is_active", "created_at")
    search_fields = ("name", "slug")
    list_filter = ("is_active",)
    prepopulated_fields = {"slug": ("name",)}
    readonly_on_change = AuditFieldsAdminMixin.readonly_on_change + ("slug",)

    fieldsets = (
        (None, {"fields": (("name", "slug"), "phone")}),
        AuditFieldsAdminMixin.META_FIELDSET,
    )
