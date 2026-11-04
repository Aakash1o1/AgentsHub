from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from unfold.admin import ModelAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    list_display = ("username", "active_vendor", "vendor_list", "is_superuser", "is_active")
    list_select_related = ("active_vendor",)
    search_fields = ("username",)
    list_filter = ("is_superuser", "is_active")
    filter_horizontal = ("vendors",)
    readonly_fields = ("username", "email", "first_name", "last_name", "last_login", "date_joined", "keycloak_id")

    fieldsets = (
        (None, {"fields": ("username",)}),
        ("Profile (from Keycloak)", {"fields": ("email", ("first_name", "last_name"))}),
        ("Access", {"fields": (("is_active", "is_superuser"),)}),
        ("Vendor access", {"fields": ("vendors", "active_vendor")}),
        ("Meta", {"fields": (("last_login", "date_joined"), "keycloak_id"), "classes": ("collapse",)}),
    )

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("vendors")

    @admin.display(description="Vendors")
    def vendor_list(self, obj):
        return ", ".join(v.name for v in obj.vendors.all())

    def get_form(self, request, obj=None, **kwargs):
        self.obj = obj
        return super().get_form(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "active_vendor" and getattr(self, "obj", None):
            kwargs["queryset"] = self.obj.vendors.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
