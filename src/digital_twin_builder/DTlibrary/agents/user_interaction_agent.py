from base_agent import BaseAgent
from transformers import pipeline, AutoModelForCausalLM, AutoTokenizer
import torch
import json
import requests
import time
import logging
import sys
import signal
from typing import Dict, Any, Optional

class UserInteractionAgent(BaseAgent):
    def __init__(self, agent_id: int, api_url: str, model = "MTSAIR/Cotype-Nano"):
        super().__init__("UserInteractionAgent")
        self.agent_id = agent_id
        self.api_url = api_url.rstrip('/')
        self.running = False
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.logger.info(f"device: {self.device}")
        try:
            # self.model = pipeline("text-generation", model= model)
            self.tokenizer = AutoTokenizer.from_pretrained(model)
            self.model = AutoModelForCausalLM.from_pretrained(
                model,
            ).to(self.device)
        except Exception as e:
            self.logger.error(f"Model loading failed: {str(e)}")
            raise

    def process_task(self, task):
        conversation_id = task.get("conversation_id", "")
        params = task.get("params", {})
        task_id = task["task_id"][:8]

        self.logger.info(f"Processing task {task_id}")
        try:
            context = self.get_conversation_context(conversation_id)
            print(context)

            text = self.tokenizer.apply_chat_template(
                context,
                enable_thinking=True,
                tokenize=False,
                add_generation_prompt=True,
            )
            model_inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
            
            generated_ids = self.model.generate(**model_inputs, max_new_tokens=params.get("max_tokens", 1000))
            
            output_ids = generated_ids[0][len(model_inputs.input_ids[0]) :]
            assistant_response = self.tokenizer.decode(output_ids, skip_special_tokens=True)

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
    parser.add_argument("--agent-id", type=int, required=True,
                       help="Agent ID (1, 2, 3, etc.)")
    parser.add_argument("--api-url", default="http://localhost:8000",
                       help="API server URL (default: http://localhost:8000)")
    parser.add_argument("--poll-interval", type=float, default=2.0,
                       help="Polling interval in seconds (default: 2.0)")
    parser.add_argument("--once", action="store_true",
                       help="Run once and exit (useful for testing)")
    parser.add_argument("--model", type=str, default="MTSAIR/Cotype-Nano",
                       help="Model from hugging face or local path to it")

    args = parser.parse_args()
    
    # Create and run agent
    agent = UserInteractionAgent(args.agent_id, args.api_url, args.model)
    
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
