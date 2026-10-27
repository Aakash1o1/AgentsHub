from vendor.models import Vendor


def admin_vendors(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    if user.is_superuser:
        vendors = Vendor.objects.all()
    else:
        vendors = user.vendors.all()
    return {
        "admin_vendors": vendors,
        "admin_active_vendor": user.active_vendor,
    }
