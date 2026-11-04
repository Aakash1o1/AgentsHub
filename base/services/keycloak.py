import time

import httpx
from django.conf import settings


class KeycloakToken:
    REFRESH_MARGIN_SECONDS = 60

    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.expires_at = 0

    @classmethod
    def for_django(cls):
        return cls("rag-django", settings.KEYCLOAK_DJANGO_CLIENT_SECRET)

    @classmethod
    def for_worker(cls):
        return cls("rag-worker", settings.KEYCLOAK_WORKER_CLIENT_SECRET)

    @staticmethod
    def token_url():
        return f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"

    async def fetch(self):
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.post(self.token_url(), data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            })
        response.raise_for_status()
        body = response.json()
        self.access_token = body["access_token"]
        self.expires_at = time.monotonic() + body["expires_in"]

    async def header(self):
        if time.monotonic() > self.expires_at - self.REFRESH_MARGIN_SECONDS:
            await self.fetch()
        return {"authorization": f"Bearer {self.access_token}"}

