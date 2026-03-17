from agents import UserInteractionAgent, DatabaseAgent, DigitalTwinAgent
from config import API_URL

def start_agents(api_url=None, models=[]):
    if api_url is None:
        api_url = API_URL
    ui_agent = UserInteractionAgent(0, api_url)
    db_agent = DatabaseAgent(1, api_url)
    dt_agent = DigitalTwinAgent(2, api_url)

def main():
    """Main entry point with command-line arguments."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Start all agents for digital twin builder")
    parser.add_argument("--api-url", default="http://localhost:8000",
                       help="API server URL (default: http://localhost:8000)")
    parser.add_argument("--poll-interval", type=float, default=2.0,
                       help="Polling interval in seconds (default: 2.0)")
    parser.add_argument("--once", action="store_true",
                       help="Run once and exit (useful for testing)")
    parser.add_argument("--model", type=str, default="abdulmannan-01/qwen-2.5-1.5b-finetuned-for-sql-generation",
                       help="Model from hugging face or local path to it")

    args = parser.parse_args()
    
    # Create and run agent
    agent = DatabaseAgent(args.agent_id, args.api_url, args.model)
    
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
