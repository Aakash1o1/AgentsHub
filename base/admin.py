from django.contrib import admin
from django.utils import timezone
from unfold.admin import ModelAdmin


class ActiveListFilter(admin.SimpleListFilter):
    title = "visibility"
    parameter_name = "visibility"
    DEFAULT = "active"

    def lookups(self, request, model_admin):
        return (("active", "Active"), ("deleted", "Deleted"), ("all", "All"))

    def selected(self):
        return self.value() or self.DEFAULT

    def queryset(self, request, queryset):
        if self.selected() == "all":
            return queryset
        return queryset.filter(is_active=self.selected() == "active")

    def choices(self, changelist):
        for lookup, title in self.lookup_choices:
            yield {
                "selected": self.selected() == lookup,
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": title,
            }


class SoftDeleteAdminMixin:
    SOFT_DELETE_ACTIONS = ["soft_delete_selected", "restore_selected"]
    actions = SOFT_DELETE_ACTIONS
    list_filter = (ActiveListFilter,)

    def has_delete_permission(self, request, obj=None):
        return False

    def set_active(self, request, queryset, active):
        return queryset.filter(is_active=not active).update(
            is_active=active, updated_by=request.user, updated_at=timezone.now()
        )

    @admin.action(description="Soft delete selected %(verbose_name_plural)s")
    def soft_delete_selected(self, request, queryset):
        count = self.set_active(request, queryset, False)
        self.message_user(request, f"{count} {self.model._meta.verbose_name_plural} soft deleted.")

    @admin.action(description="Restore selected %(verbose_name_plural)s")
    def restore_selected(self, request, queryset):
        count = self.set_active(request, queryset, True)
        self.message_user(request, f"{count} {self.model._meta.verbose_name_plural} restored.")


class AuditFieldsAdminMixin:
    # Paste this as the last entry of an admin's `fieldsets`.
    META_FIELDSET = ("Meta", {
        "fields": (("created_by", "created_at"), ("updated_by", "updated_at"), "is_active"),
        "classes": ("collapse",),
    })

    ALWAYS_READONLY = ("created_at", "updated_at")

    # Settable while creating a row, frozen afterwards. Subclasses extend it.
    readonly_on_change = ("created_by", "updated_by")

    def get_readonly_fields(self, request, obj=None):
        readonly = tuple(super().get_readonly_fields(request, obj))
        readonly += tuple(f for f in self.ALWAYS_READONLY if f not in readonly)
        if obj is not None:                          # obj is None on the add page
            readonly += tuple(f for f in self.readonly_on_change if f not in readonly)
        return readonly

    def auto_fill_values(self, request):
        return {"created_by": request.user, "updated_by": request.user}

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is None:
            for name, value in self.auto_fill_values(request).items():
                field = form.base_fields.get(name)
                if field is not None:
                    field.initial = value
                    field.disabled = True
                    field.widget.can_add_related = False
                    field.widget.can_change_related = False
                    field.widget.can_delete_related = False
        return form

    def save_model(self, request, obj, form, change):
        values = {"updated_by": request.user} if change else self.auto_fill_values(request)
        for name, value in values.items():
            setattr(obj, name, value)
        super().save_model(request, obj, form, change)


class VendorScopedAdmin(AuditFieldsAdminMixin, ModelAdmin):
    vendor_lookup = "vendor"

    def get_queryset(self, request):
        return self.scope_to_vendor(super().get_queryset(request), request.user, self.vendor_lookup)

    @staticmethod
    def scope_to_vendor(qs, user, lookup="vendor"):
        active = user.active_vendor
        if user.is_superuser and active is None:
            return qs
        if active is None:
            return qs.none()
        return qs.filter(**{lookup: active})
