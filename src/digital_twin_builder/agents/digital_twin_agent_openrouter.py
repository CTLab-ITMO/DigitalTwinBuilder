"""
Digital twin agent backed by a remote OpenRouter model.

Same task protocol as digital_twin_agent.py (polls the API, adds the answer
back to the conversation), but the LLM call goes to OpenRouter instead of a
local transformers model, so no GPU or Slurm allocation is needed.
"""
import sys
import os
import importlib.util
from pathlib import Path

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
from digital_twin_builder.openrouter_client import OpenRouterClient


class DigitalTwinAgentOpenRouter(BaseAgent):
    def __init__(self):
        super().__init__("DigitalTwinAgentOpenRouter")
        self.agent_id = DT_AGENT_INDEX
        self.api_url = API_URL.rstrip('/')
        self.running = False
        self.base_url = OPENROUTER_BASE_URL.rstrip('/')
        self.model = OPENROUTER_MODEL
        self.client = OpenRouterClient(
            model=self.model,
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            site_url=OPENROUTER_SITE_URL,
            app_name=OPENROUTER_APP_NAME,
            ignore_providers=OPENROUTER_IGNORE_PROVIDERS,
            logger=self.logger,
        )
        self.logger.info(f"Using OpenRouter model {self.model} at {self.base_url}")
        if self.client.ignore_providers:
            self.logger.info(
                f"Avoiding providers: {', '.join(self.client.ignore_providers)}")

    def process_task(self, task):
        conversation_id = task.get("conversation_id", "")
        params = task.get("params", {})
        task_id = task["task_id"][:8]

        self.logger.info(f"Processing task {task_id}")
        try:
            context = self.get_conversation_context(conversation_id)
            if not context:
                raise RuntimeError(f"Empty conversation context for {conversation_id}")

            assistant_response = self.client.chat(
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
