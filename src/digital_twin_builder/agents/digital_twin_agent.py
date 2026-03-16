from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
import sys
import signal
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from digital_twin_builder.agents import BaseAgent
from digital_twin_builder.config import API_URL, DT_AGENT_INDEX, DT_AGENT_MODEL

class DigitalTwinAgent(BaseAgent):
    def __init__(self):
        super().__init__("DigitalTwinAgent")
        self.agent_id = DT_AGENT_INDEX
        self.api_url = API_URL.rstrip('/')
        self.running = False
        try:
            # self.model = pipeline("text-generation", model= model)
            self.tokenizer = AutoTokenizer.from_pretrained(DT_AGENT_MODEL)
            self.model = AutoModelForCausalLM.from_pretrained(
                DT_AGENT_MODEL, 
                device_map="auto", 
                torch_dtype=torch.bfloat16
            )
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
