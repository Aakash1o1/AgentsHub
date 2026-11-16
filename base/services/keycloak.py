import time

import httpx
from asgiref.sync import async_to_sync
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



class KeycloakAdmin:
    ADMIN_GROUP = "temporal-admins"

    def __init__(self):
        self.token = KeycloakToken.for_django()
        self.group_id = None

    @staticmethod
    def base_url():
        return f"{settings.KEYCLOAK_URL}/admin/realms/{settings.KEYCLOAK_REALM}"

    def call(self, method, path, **kwargs):
        headers = async_to_sync(self.token.header)()
        response = httpx.request(method, self.base_url() + path, headers=headers, timeout=10, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    def admin_group_id(self):
        if self.group_id is None:
            groups = self.call("GET", "/groups", params={"search": self.ADMIN_GROUP, "exact": "true"})
            self.group_id = next((group["id"] for group in groups if group["name"] == self.ADMIN_GROUP), None)
        return self.group_id

    def set_admin_group(self, user):
        group_id = self.admin_group_id()
        if not user.keycloak_id or group_id is None:
            return False
        method = "PUT" if user.is_superuser and user.is_active else "DELETE"
        self.call(method, f"/users/{user.keycloak_id}/groups/{group_id}")
        return True
