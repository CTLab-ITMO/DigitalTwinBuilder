"""
Digital twin agent backed by a remote OpenRouter model.

Same task protocol as digital_twin_agent.py (polls the API, adds the answer
back to the conversation), but the LLM call goes to OpenRouter instead of a
local transformers model, so no GPU or Slurm allocation is needed.
"""
import sys
import os
import time
import importlib.util
from pathlib import Path

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

# Import BaseAgent straight from base_agent.py instead of via the `agents`
# package: the package __init__ also imports the local-model agents, which pull
# in transformers/torch. This agent deliberately needs neither.
_spec = importlib.util.spec_from_file_location(
    "digital_twin_builder_base_agent", Path(__file__).with_name("base_agent.py")
)
_base_agent_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base_agent_module)
BaseAgent = _base_agent_module.BaseAgent

from digital_twin_builder.config import (
    API_URL,
    DT_AGENT_INDEX,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    OPENROUTER_SITE_URL,
    OPENROUTER_APP_NAME,
    OPENROUTER_IGNORE_PROVIDERS,
)

# Retry transient provider failures (rate limits, upstream 5xx).
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4


class DigitalTwinAgentOpenRouter(BaseAgent):
    def __init__(self):
        super().__init__("DigitalTwinAgentOpenRouter")
        self.agent_id = DT_AGENT_INDEX
        self.api_url = API_URL.rstrip('/')
        self.running = False
        self.base_url = OPENROUTER_BASE_URL.rstrip('/')
        self.model = OPENROUTER_MODEL
        if not OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY is not set")
        self.headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        if OPENROUTER_SITE_URL:
            self.headers["HTTP-Referer"] = OPENROUTER_SITE_URL
        if OPENROUTER_APP_NAME:
            self.headers["X-Title"] = OPENROUTER_APP_NAME
        self.ignore_providers = [
            p.strip() for p in OPENROUTER_IGNORE_PROVIDERS.split(",") if p.strip()
        ]
        self.logger.info(f"Using OpenRouter model {self.model} at {self.base_url}")
        if self.ignore_providers:
            self.logger.info(f"Avoiding providers: {', '.join(self.ignore_providers)}")

    def generate(self, messages, max_tokens=1000, temperature=0.7):
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
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=300,
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
                    # Some upstream providers (observed: Novita) sporadically
                    # answer 200 with content=null. There is no answer in that
                    # response, so retry instead of handing null to the API
                    # (which rejects it with a 422 and loses the task).
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
                f"OpenRouter attempt {attempt}/{MAX_ATTEMPTS} failed: {last_error}"
            )
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(2 ** attempt, 15))

        raise RuntimeError(f"OpenRouter request failed after {MAX_ATTEMPTS} attempts: {last_error}")

    def process_task(self, task):
        conversation_id = task.get("conversation_id", "")
        params = task.get("params", {})
        task_id = task["task_id"][:8]

        self.logger.info(f"Processing task {task_id}")
        try:
            context = self.get_conversation_context(conversation_id)
            if not context:
                raise RuntimeError(f"Empty conversation context for {conversation_id}")

            assistant_response = self.generate(
                context,
                max_tokens=params.get("max_tokens", 1000),
                temperature=params.get("temperature", 0.7),
            )

            self.add_to_conversation(
                conversation_id,
                role="assistant",
                content=assistant_response,
            )

            return assistant_response

        except Exception as e:
            self.logger.error(str(self.api_url))
            self.logger.error(f"Interview failed: {str(e)}")
            raise


def main():
    """Main entry point with command-line arguments."""
    import argparse

    parser = argparse.ArgumentParser(description="OpenRouter-backed digital twin agent")
    parser.add_argument("--poll-interval", type=float, default=2.0,
                       help="Polling interval in seconds (default: 2.0)")
    parser.add_argument("--once", action="store_true",
                       help="Run once and exit (useful for testing)")

    args = parser.parse_args()

    agent = DigitalTwinAgentOpenRouter()

    def signal_handler(sig, frame):
        agent.stop()
        sys.exit(0)

    import signal
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.once:
        agent.run_once()
    else:
        agent.run(interval=args.poll_interval)


if __name__ == "__main__":
    main()
