import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rag.settings')

django_asgi_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

from chat.api.routing import websocket_urlpatterns as chat_websockets
from scraper.api.routing import websocket_urlpatterns as scraper_websockets

application = ProtocolTypeRouter({
    "http": django_asgi_application,
    "websocket": AuthMiddlewareStack(URLRouter(chat_websockets + scraper_websockets)),
})
