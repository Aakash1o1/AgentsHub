from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


class Broadcaster:
    EVENT_TYPE = None

    @classmethod
    def publish(cls, group, payload):
        layer = get_channel_layer()
        if layer is None or not group:
            return
        async_to_sync(layer.group_send)(group, {"type": cls.EVENT_TYPE, "payload": payload})
