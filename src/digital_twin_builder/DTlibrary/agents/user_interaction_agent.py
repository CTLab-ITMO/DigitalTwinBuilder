from base_agent import BaseAgent
from transformers import pipeline
import json
import requests
import time
import logging
import sys
import signal
from typing import Dict, Any, Optional

class UserInteractionAgent(BaseAgent):
    def __init__(self, agent_id: int, api_url: str):
        super().__init__("UserInteractionAgent")
        self.agent_id = agent_id
        self.api_url = api_url.rstrip('/')
        self.running = False

        try:
            self.model = pipeline("text-generation", model="MTSAIR/Cotype-Nano")
        except Exception as e:
            self.log(f"Model loading failed: {str(e)}", "error")
            raise

    def process_task(self, task):
        prompt = task["prompt"]
        params = task.get("params", {})
        task_id = task["task_id"][:8]
        
        logger.info(f"Processing task {task_id}: {prompt[:50]}...")
        
        try:
            response = self.model(
                prompt,
                max_length=2048,
                num_return_sequences=1
            )
            assistant_response = response[0]['generated_text']

            if assistant_response.startswith(user_input):
                assistant_response = assistant_response[len(user_input):].strip()
            assistant_response = response.replace(, "").strip()
            
            return assistant_response

        except Exception as e:
            self.log(f"Interview failed: {str(e)}", "error")
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
    
    args = parser.parse_args()
    
    # Create and run agent
    agent = UserInteractionAgent(args.agent_id, args.api_url)
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        agent.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if args.once:
        logger.info("Running in single-task mode")
        agent.run_once()
    else:
        agent.run(interval=args.poll_interval)


if __name__ == "__main__":
    main()
