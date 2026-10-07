from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
import sys
import signal
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from digital_twin_builder.agents import BaseAgent
from digital_twin_builder.config import API_URL, UI_AGENT_INDEX, UI_AGENT_MODEL
from digital_twin_builder.interview_context import fit_context

class UserInteractionAgent(BaseAgent):
    def __init__(self):
        super().__init__("UserInteractionAgent")
        self.agent_id = UI_AGENT_INDEX
        self.api_url = API_URL.rstrip('/')
        self.running = False
        try:
            # self.model = pipeline("text-generation", model= model)
            self.tokenizer = AutoTokenizer.from_pretrained(UI_AGENT_MODEL)
            self.model = AutoModelForCausalLM.from_pretrained(
                UI_AGENT_MODEL,
                device_map="auto"
            )
            # Inference, not training: eval mode disables dropout, so a turn is
            # reproducible and does not carry the training path's extra state.
            self.model.eval()
            self.logger.info(f"Model {UI_AGENT_MODEL} loaded")
        except Exception as e:
            self.logger.error(f"Model {UI_AGENT_MODEL} loading failed: {str(e)}")
            raise

    def process_task(self, task):
        conversation_id = task.get("conversation_id", "")
        params = task.get("params", {})
        task_id = task["task_id"][:8]

        self.logger.info(f"Processing task {task_id}")
        try:
            context = self.get_conversation_context(conversation_id) or []
            # The whole conversation is re-fed every turn, and a repair turn's
            # correction prompt embeds the previous reply on top of it, so the
            # prompt grows without bound — and the model's attention buffer grows
            # with its square, which is how a session's second turn ran the GPU
            # out of memory. `fit_context` drops the reasoning blocks and bounds
            # the prompt; the first turn, well under the cap, is untouched.
            before = sum(len(m["content"]) for m in context)
            context = fit_context(context)
            after = sum(len(m["content"]) for m in context)
            if after < before:
                self.logger.info(
                    f"Interview prompt {before} -> {after} chars "
                    f"({len(context)} messages)")

            text = self.tokenizer.apply_chat_template(
                context,
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
    parser.add_argument("--model", type=str, default="HuggingFaceTB/SmolLM3-3B",
                       help="Model from hugging face or local path to it")

    args = parser.parse_args()
    
    # Create and run agent
    agent = UserInteractionAgent()
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
