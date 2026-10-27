from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from vendor.api.views import AdminSetVendorView

urlpatterns = [
    path('', include('chat.api.urls')),
    path('api/v1/chat/', include('chat.api.urls')),
    path('api/v1/scraper/', include('scraper.api.urls')),
    path('api/v1/agent/', include('agent.api.urls')),
    path('api/v1/analysis/', include('analysis.api.urls')),
    path('admin/set-vendor/', AdminSetVendorView.as_view(), name='admin_set_vendor'),
    path('admin/', admin.site.urls),
    path('o/', include('authentication.api.urls')),
]

# Django only serves uploaded files itself in DEBUG; a real deploy hands this to nginx
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
