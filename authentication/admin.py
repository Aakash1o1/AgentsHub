from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Permission
from django.db.models import Q
from unfold.admin import ModelAdmin

from authentication.services.keycloak_users import TemporalAdmins
from chat.services.access import TaskAccess
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    list_display = ("username", "active_vendor", "vendor_list", "is_superuser", "is_active")
    list_select_related = ("active_vendor",)
    search_fields = ("username",)
    list_filter = ("is_superuser", "is_active")
    filter_horizontal = ("vendors", "user_permissions")
    readonly_fields = ("username", "first_name", "last_name")
    EXTRA_PERMISSIONS = (TaskAccess.PERMISSION,)

    fieldsets = (
        ("Profile", {"fields": ("username", ("first_name", "last_name"))}),
        ("Access", {"fields": (("is_active", "is_superuser"),)}),
        ("Extra permissions", {"fields": ("user_permissions",)}),
        ("Vendors", {"fields": ("vendors", "active_vendor")}),
    )

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("vendors")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if {"is_superuser", "is_active"} & set(form.changed_data):
            error = TemporalAdmins.sync(obj)
            if error:
                self.message_user(request, error, messages.WARNING)

    @admin.display(description="Vendors")
    def vendor_list(self, obj):
        return ", ".join(v.name for v in obj.vendors.all())

    def get_form(self, request, obj=None, **kwargs):
        self.obj = obj
        return super().get_form(request, obj, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "user_permissions":
            query = Q()
            for name in self.EXTRA_PERMISSIONS:
                app, codename = name.split(".")
                query |= Q(content_type__app_label=app, codename=codename)
            kwargs["queryset"] = Permission.objects.filter(query)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "active_vendor" and getattr(self, "obj", None):
            kwargs["queryset"] = self.obj.vendors.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
