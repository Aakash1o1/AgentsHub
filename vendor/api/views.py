from django.shortcuts import redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from vendor.models import Vendor


class AdminSetVendorView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        vendor_id = request.POST.get("vendor_id")
        if user.is_superuser:
            if vendor_id == "all":
                user.active_vendor = None
            else:
                user.active_vendor = Vendor.objects.filter(id=vendor_id).first() or user.active_vendor
            user.save()
        else:
            vendor = user.vendors.filter(id=vendor_id).first()
            if vendor:
                user.active_vendor = vendor
                user.save()
        return redirect(request.META.get("HTTP_REFERER") or "admin:index")
