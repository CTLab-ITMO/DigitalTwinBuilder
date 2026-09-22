import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class GrafanaClient:

    def __init__(self):
        self.base_url = os.getenv("GRAFANA_URL", "http://grafana:3000")
        self._user = os.getenv("GRAFANA_USER", "admin")
        self._password = os.getenv("GRAFANA_PASSWORD", "admin")
        self._api_key = os.getenv("GRAFANA_API_KEY", "")
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
                self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers)
            else:
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    headers=headers,
                    auth=(self._user, self._password),
                )
        return self._client

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        import asyncio

        last_exc = None
        for attempt in range(3):
            try:
                client = await self._ensure_client()
                resp = await client.request(method, path, **kwargs)
                return resp
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise last_exc

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def health_check(self) -> bool:
        try:
            resp = await self._request("GET", "/api/health")
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("Grafana health check failed: %s", exc)
            return False

    async def get_dashboard(self, uid: str) -> Optional[dict]:
        resp = await self._request("GET", f"/api/dashboards/uid/{uid}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def create_or_update_dashboard(self, dashboard_json: dict, overwrite: bool = True) -> str:
        payload = {
            "dashboard": dashboard_json,
            "overwrite": overwrite,
        }
        resp = await self._request("POST", "/api/dashboards/db", json=payload)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Grafana dashboard %s: %s", data.get("status", "?"), data.get("url", ""))
        return data.get("url", "")

    async def delete_dashboard(self, uid: str) -> bool:
        resp = await self._request("DELETE", f"/api/dashboards/uid/{uid}")
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    async def create_annotation(
        self,
        dashboard_uid: str,
        time_ms: int,
        tags: Optional[list[str]] = None,
        text: str = "",
        panel_id: int = 0,
    ) -> Optional[dict]:
        payload = {
            "dashboardUID": dashboard_uid,
            "panelId": panel_id,
            "time": time_ms,
            "timeEnd": time_ms,
            "tags": tags or [],
            "text": text,
        }
        try:
            resp = await self._request("POST", "/api/annotations", json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Failed to create Grafana annotation: %s", exc)
            return None

    async def create_email_notification_channel(self, name: str, addresses: list[str]) -> Optional[dict]:
        payload = {
            "name": name,
            "type": "email",
            "settings": {"addresses": ",".join(addresses)},
        }
        try:
            resp = await self._request("POST", "/api/alert-notifications", json=payload)
            if resp.status_code == 409:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Failed to create email notification channel: %s", exc)
            return None
