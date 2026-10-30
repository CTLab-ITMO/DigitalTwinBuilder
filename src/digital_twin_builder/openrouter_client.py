"""OpenRouter chat client shared by the remote agents.

The HTTP call, retry policy and empty-content handling are the same for every
agent that talks to OpenRouter, so they live here instead of being copied into
each agent. The local-model agents deliberately do not import this module.

`content` may arrive empty even on HTTP 200 (some upstream providers generate
and bill the completion but never serialize it), so an empty answer is retried
rather than handed back to the API — which would reject it and lose the task.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable

import requests

# Retry transient provider failures (rate limits, upstream 5xx).
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4


class OpenRouterClient:
    """A minimal OpenAI-compatible client for OpenRouter chat completions."""

    def __init__(self, model: str, api_key: str, base_url: str,
                 site_url: str = "", app_name: str = "",
                 ignore_providers: Iterable[str] | str | None = None,
                 timeout: int = 300, max_attempts: int = MAX_ATTEMPTS,
                 logger: logging.Logger | None = None):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.logger = logger or logging.getLogger(__name__)
        if isinstance(ignore_providers, str):
            ignore_providers = ignore_providers.split(",")
        self.ignore_providers = [
            p.strip() for p in (ignore_providers or []) if p.strip()
        ]
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if site_url:
            self.headers["HTTP-Referer"] = site_url
        if app_name:
            self.headers["X-Title"] = app_name

    def chat(self, messages, max_tokens: int = 1000,
             temperature: float = 0.7) -> str:
        """Return the assistant's text for `messages`, retrying transient errors."""
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if self.ignore_providers:
            # Keep routing deterministic-ish: skip upstreams known to drop the
            # completion text (see OPENROUTER_IGNORE_PROVIDERS).
            payload["provider"] = {"ignore": self.ignore_providers}

        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as e:
                last_error = f"Request failed: {e}"
            else:
                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices") or []
                    if not choices:
                        raise RuntimeError(f"OpenRouter returned no choices: {data}")
                    content = choices[0]["message"].get("content")
                    if isinstance(content, str) and content.strip():
                        return content
                    last_error = (
                        f"empty content (finish_reason={choices[0].get('finish_reason')}, "
                        f"provider={data.get('provider')}, "
                        f"completion_tokens="
                        f"{(data.get('usage') or {}).get('completion_tokens')})"
                    )
                else:
                    last_error = f"HTTP {response.status_code}: {response.text}"
                    if response.status_code not in RETRYABLE_STATUS:
                        raise RuntimeError(f"OpenRouter request failed: {last_error}")

            self.logger.warning(
                f"OpenRouter attempt {attempt}/{self.max_attempts} failed: {last_error}"
            )
            if attempt < self.max_attempts:
                time.sleep(min(2 ** attempt, 15))

        raise RuntimeError(
            f"OpenRouter request failed after {self.max_attempts} attempts: {last_error}"
        )
