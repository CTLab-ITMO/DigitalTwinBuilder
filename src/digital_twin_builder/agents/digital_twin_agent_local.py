#from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
#import torch
import sys
import signal
import os
from openai import OpenAI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from digital_twin_builder.agents import BaseAgent
from digital_twin_builder.config import API_URL, DT_AGENT_INDEX, DT_AGENT_MODEL

class DigitalTwinAgent(BaseAgent):
    def __init__(self):
        super().__init__("DigitalTwinAgent")
        self.agent_id = DT_AGENT_INDEX
        self.api_url = API_URL.rstrip('/')
        self.running = False

        api_key = os.getenv("DASHSCOPE_API_KEY")  # как в примере Model Studio
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        )
        self.qwen_model = os.getenv("QWEN_MODEL_NAME", "qwen3-coder-flash-2025-07-28")

    def process_task(self, task):
        conversation_id = task.get("conversation_id", "")
        params = task.get("params", {})
        task_id = task["task_id"][:8]

        self.logger.info(f"Processing task {task_id}")
        try:
            context = self.get_conversation_context(conversation_id)
            # context — список сообщений [{"role": "...", "content": "..."}]

            completion = self.client.chat.completions.create(
                model=self.qwen_model,
                messages=context,
                max_tokens=params.get("max_tokens", 1000),
            )

            assistant_response = completion.choices[0].message.content

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
    
    parser = argparse.ArgumentParser(description="Simple LLM Agent")
    parser.add_argument("--poll-interval", type=float, default=2.0,
                       help="Polling interval in seconds (default: 2.0)")
    parser.add_argument("--once", action="store_true",
                       help="Run once and exit (useful for testing)")

    args = parser.parse_args()
    
    # Create and run agent
    agent = DigitalTwinAgent()
    
    # Handle graceful shutdown
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

