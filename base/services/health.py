from django.core.cache import cache
from django.utils import timezone

from base.services.broadcast import Broadcaster
from base.services.temporal import TemporalClient


class TemporalHealth(Broadcaster):
    EVENT_TYPE = "temporal.health"
    GROUP = "temporal_health"
    CACHE_KEY = "temporal_health"

    @classmethod
    def check(cls):
        health = {**TemporalClient.health(), "checked_at": timezone.now().isoformat()}
        cache.set(cls.CACHE_KEY, health, timeout=None)
        cls.publish(cls.GROUP, health)
        return health

    @classmethod
    def latest(cls):
        return cache.get(cls.CACHE_KEY)
