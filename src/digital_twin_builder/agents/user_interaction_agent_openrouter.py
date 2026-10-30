"""
Interview agent backed by DeepSeek V4.1 Flash on OpenRouter.

Same task protocol as `user_interaction_agent.py` — polls the API for a task,
reads the conversation, posts the answer back — but the LLM call goes to
OpenRouter instead of a local transformers model, so no GPU or Slurm allocation
is needed.

Run it from the repository root as a file (the `-m` form would execute the
`agents` package __init__, which imports the local torch agents):

    python src/digital_twin_builder/agents/user_interaction_agent_openrouter.py

It claims the same `UI_AGENT_INDEX` slot as the local interview agent, so run
one or the other, never both.
"""
import importlib.util
import os
import signal
import sys
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
    UI_AGENT_INDEX,
    UI_AGENT_OPENROUTER_MODEL,
    UI_MAX_TOKENS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_SITE_URL,
    OPENROUTER_APP_NAME,
    OPENROUTER_IGNORE_PROVIDERS,
)
from digital_twin_builder.interview_context import fit_context
from digital_twin_builder.openrouter_client import OpenRouterClient


class UserInteractionAgentOpenRouter(BaseAgent):
    def __init__(self, model: str | None = None):
        super().__init__("UserInteractionAgentOpenRouter")
        self.agent_id = UI_AGENT_INDEX
        self.api_url = API_URL.rstrip('/')
        self.running = False
        self.model = model or UI_AGENT_OPENROUTER_MODEL
        self.client = OpenRouterClient(
            model=self.model,
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            site_url=OPENROUTER_SITE_URL,
            app_name=OPENROUTER_APP_NAME,
            ignore_providers=OPENROUTER_IGNORE_PROVIDERS,
            logger=self.logger,
        )
        self.logger.info(f"Using OpenRouter interview model {self.model}")

    def process_task(self, task):
        conversation_id = task.get("conversation_id", "")
        params = task.get("params", {})
        task_id = task["task_id"][:8]

        self.logger.info(f"Processing task {task_id}")
        try:
            context = self.get_conversation_context(conversation_id) or []
            # Keep the assembled prompt bounded exactly as the local interview
            # agent does: this agent re-reads the whole conversation every turn,
            # and the broker's repair turns add to it.
            before = sum(len(m["content"]) for m in context)
            context = fit_context(context)
            after = sum(len(m["content"]) for m in context)
            if after < before:
                self.logger.info(
                    f"Interview prompt {before} -> {after} chars "
                    f"({len(context)} messages)")

            assistant_response = self.client.chat(
                context,
                max_tokens=params.get("max_tokens", UI_MAX_TOKENS),
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

    parser = argparse.ArgumentParser(
        description="OpenRouter-backed interview agent (DeepSeek V4.1 Flash)")
    parser.add_argument("--poll-interval", type=float, default=2.0,
                        help="Polling interval in seconds (default: 2.0)")
    parser.add_argument("--once", action="store_true",
                        help="Run once and exit (useful for testing)")
    parser.add_argument("--model", default=None,
                        help="OpenRouter model slug (default: "
                             "UI_AGENT_OPENROUTER_MODEL)")

    args = parser.parse_args()

    agent = UserInteractionAgentOpenRouter(args.model)

    def signal_handler(sig, frame):
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.once:
        agent.run_once()
    else:
        agent.run(interval=args.poll_interval)


if __name__ == "__main__":
    main()
