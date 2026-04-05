# System workflow
> **_NOTE:_**  If you want access either to the server or cluster, send me your public ssh key on tg: [@gozebone](https://t.me/gozebone)
## How distributed system works
There are 3 components to the system:
- Cluster with agents
- Server with database and api
- Locally ran streamlit control panel (could also be on server)

Cluster and Streamlit are sending http requests to api, in simple terms streamlit adds tasks and agent on cluster completes task and sends an answer.

## Conversation Index System

The application uses a two-dimensional conversation tracking system:

```python
# Structure: conversations[agent_id][conv_idx]
# - agent_id: Which agent the conversation is with (0, 1, 2, etc.)
# - conv_idx: Which conversation thread with that agent (0, 1, 2, etc.)
```

**Key Points:**
- `agent_id` identifies the agent (e.g., 0=UI Agent, 1=Database Agent, 2=Digital Twin Agent)
- `conv_idx` is the conversation index for multi-turn tasks with the same agent
- Each agent can have multiple parallel conversations tracked by `conv_idx`
- Default `conv_idx` is 0 for initial conversations

**Example:**
```python
# Digital Twin Agent has two conversation types:
st.session_state.conversations[2][0]  # Configuration conversation
st.session_state.conversations[2][1]  # Simulation conversation
```


### Example of full communication workflow:
Streamlit side sending request to the agent:
```python
agent_id = 0 # UI Agent (now starts from 0, not 1)
conv_idx = 0 # First conversation with this agent

# Create conversation with conv_idx
st.session_state.conversations[agent_id][conv_idx] = create_new_conversation(
    st.session_state.session_id, 
    agent_id, 
    prompts.system.example_agent_prompt,
    conv_idx  # Important: pass conv_idx to track this conversation
)

# Add user message
response = add_message_to_conversation(
    st.session_state.conversations[agent_id][conv_idx],
    role="user",
    content=prompts.user.example_make_agent_prompt(user_input),
)

# Submit task with conv_idx
if response is not None:
    submit_task(agent_id, conv_idx, st.session_state.conversations[agent_id][conv_idx], params)
```

**Note:** Agent IDs start from 0 (0=UI Agent, 1=Database Agent, 2=Digital Twin Agent).

Cluster side:
```python
class DatabaseAgent(BaseAgent):
    def __init__(self, agent_id: int, api_url: str, model="filepath to the agent (can be url, but often does not work)"):
        super().__init__("DatabaseAgent")
        self.agent_id = agent_id
        self.api_url = api_url.rstrip('/')
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.logger.info(f"device: {self.device}")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model)
            self.model = AutoModelForCausalLM.from_pretrained(
                model,
            ).to(self.device)
        except Exception as e:
            self.logger.error(f"Model loading failed: {str(e)}")
            raise

    def process_task(self, task):
        conversation_id = task.get("conversation_id", "")
        conv_idx = task.get("conv_idx", 0)  # Get conversation index from task
        params = task.get("params", {})
        task_id = task["task_id"][:8]

        self.logger.info(f"Processing task {task_id} for conv_idx {conv_idx}")
        try:
            context = self.get_conversation_context(conversation_id)

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
            ) # adds assistant answer to database

            return assistant_response

        except Exception as e:
            self.logger.error(str(self.api_url))
            self.logger.error(f"Interview failed: {str(e)}")
            raise
```

And finally getting agent answer on streamlit side:
```python
# submit_chat_to_agent created background polling task, which will push to st.session_state.response_queue when answer was get
while not st.session_state.response_queue.empty():
    task = st.session_state.response_queue.get()
    # task includes conv_idx to know which conversation thread to update
    process_incoming_task(task)
```

**Processing tasks with conv_idx:**
```python
def process_incoming_task(task):
    result = task.get("result", "")
    agent_id = task["agent_id"]
    conv_idx = task["conv_idx"]  # Extract conversation index
    st.session_state.waiting_for_agent[agent_id][conv_idx] = False
    
    # Route to correct processor based on agent_id AND conv_idx
    if agent_id == 0:
        process_interview_task(result)
    elif agent_id == 1:
        process_database_task(result)
    elif agent_id == 2:  # Digital Twin Agent
        if conv_idx == 0:
            process_dt_conf_task(result)  # Configuration
        elif conv_idx == 1:
            process_dt_sim_task(result)   # Simulation
        else:
            print(f"No task processor defined for agent {agent_id} conv_idx {conv_idx}")
```

For more implementation details please see [streamlit-app.py](src/digital_twin_builder/streamlit-app.py), [prompts/](src/digital_twin_builder/prompts/), [agents/](src/digital_twin_builder/DTlibrary/agents/), [api_utils.py](src/digital_twin_builder/api_utils.py)

## Running the System

### Start the UI Locally

To run the Streamlit control panel on your local machine, follow these steps:

#### 1. Clone the Repository (if not already done)

```bash
git clone https://github.com/CTLab-ITMO/DigitalTwinBuilder.git
cd DigitalTwinBuilder
```

#### 2. Set Up Environment Configuration

Copy the example environment file and configure it for your needs:

```bash
cp .env.example .env
```

Then edit `.env` with your preferred editor:

```bash
nano .env
# or
vim .env
```

**Key environment variables to configure:**

```bash
# API Server URL - where the backend API is running
API_URL=http://localhost:8000          # For local development
# API_URL=http://188.119.67.226:8000  # For remote server

# Agent Models - paths to your LLM models
UI_AGENT_MODEL=models/SmolLM3-3B
DB_AGENT_MODEL=models/SmolLM3-3B
DT_AGENT_MODEL=models/QwenCoder-30B

# If using remote API, you can leave models empty (agents on server will use their own models)
UI_AGENT_MODEL=
DB_AGENT_MODEL=
DT_AGENT_MODEL=

# Database Configuration (update if using local database)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

#### 3. Install Dependencies

**Using virtual environment (recommended):**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Or using poetry (if available):**
```bash
poetry install
```

#### 4. Start Backend Services (Optional)

If you're running the entire stack locally (not just the UI), start the database and API server first:

```bash
# Start PostgreSQL and Grafana with Docker
docker compose up -d dt-postgres dt-grafana

# Start the API server
python src/digital_twin_builder/api-server.py
```

#### 5. Start the Streamlit UI

Run the Streamlit application:

```bash
streamlit run src/digital_twin_builder/streamlit-app.py
```

The UI will open in your browser at `http://localhost:8501` by default.

**Alternative: Run with custom Streamlit settings:**
```bash
streamlit run src/digital_twin_builder/streamlit-app.py \
  --server.port 8501 \
  --server.headless true
```

#### 6. Start Agents (If Running Locally)

If you're running agents on your local machine instead of a cluster:

```bash
# Start all agents
python src/digital_twin_builder/agents_starter.py --api-url http://localhost:8000

# Or start individual agents
python -m digital_twin_builder.agents.user_interaction_agent --api-url http://localhost:8000
python -m digital_twin_builder.agents.database_agent --api-url http://localhost:8000
python -m digital_twin_builder.agents.digital_twin_agent --api-url http://localhost:8000
```

### Using Docker (Recommended for Full Stack)

If you want to run the complete system including database and cameras:

```bash
# Copy and configure environment file
cp .env.example .env
# Edit .env with your settings

# Start all services
docker compose up -d

# View logs
docker compose logs -f dt-python

# Restart services
docker compose up --build -d && docker compose restart
```

### Troubleshooting

**UI won't start:**
- Check that all dependencies are installed: `pip install -r requirements.txt`
- Ensure port 8501 is not in use by another application
- Verify `.env` file exists and is properly configured

**Can't connect to API:**
- Verify `API_URL` in `.env` points to the correct server
- Check if the API server is running: `curl http://localhost:8000/health`
- Ensure network connectivity if using remote server

**Agent not responding:**
- Check agent logs: `python -m digital_twin_builder.agents.database_agent --once`
- Verify model paths are correct and models are accessible
- Ensure agent indices in `.env` match the expected values

---

## How to add new agent

Adding a new agent to the system involves several steps: creating the agent class, configuring it, registering it with the API, and integrating it into the Streamlit UI.

### 1. Create the Agent Class

Create a new Python file in the `agents/` directory (e.g., `my_new_agent.py`). Your agent should:

- Inherit from `BaseAgent`
- Implement the `__init__` method to load models and set up configuration
- Implement the `process_task` method to handle incoming tasks

**Example:**
```python
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from digital_twin_builder.agents import BaseAgent
from digital_twin_builder.config import API_URL, MY_AGENT_INDEX, MY_AGENT_MODEL

class MyNewAgent(BaseAgent):
    def __init__(self):
        super().__init__("MyNewAgent")
        self.agent_id = MY_AGENT_INDEX
        self.api_url = API_URL.rstrip('/')
        self.running = False
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(MY_AGENT_MODEL)
            self.model = AutoModelForCausalLM.from_pretrained(
                MY_AGENT_MODEL,
                device_map="auto"
            )
            self.logger.info(f"Model {MY_AGENT_MODEL} loaded")
        except Exception as e:
            self.logger.error(f"Model loading failed: {str(e)}")
            raise

    def process_task(self, task):
        """Process incoming task and return result"""
        conversation_id = task.get("conversation_id", "")
        conv_idx = task.get("conv_idx", 0)  # Don't forget conversation index!
        params = task.get("params", {})
        task_id = task["task_id"][:8]

        self.logger.info(f"Processing task {task_id} for conv_idx {conv_idx}")
        try:
            # Get conversation context
            context = self.get_conversation_context(conversation_id)
            
            # Process with your model
            text = self.tokenizer.apply_chat_template(
                context,
                tokenize=False,
                add_generation_prompt=True,
            )
            model_inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
            
            generated_ids = self.model.generate(
                **model_inputs, 
                max_new_tokens=params.get("max_tokens", 1000)
            )
            
            output_ids = generated_ids[0][len(model_inputs.input_ids[0]):]
            assistant_response = self.tokenizer.decode(output_ids, skip_special_tokens=True)
            
            # Save response to conversation
            self.add_to_conversation(
                conversation_id,
                role="assistant",
                content=assistant_response,
            )
            
            return assistant_response

        except Exception as e:
            self.logger.error(f"Task processing failed: {str(e)}")
            raise


def main():
    """Main entry point"""
    import argparse
    import signal

    parser = argparse.ArgumentParser(description="My New Agent")
    parser.add_argument("--poll-interval", type=float, default=2.0,
                       help="Polling interval in seconds (default: 2.0)")
    parser.add_argument("--once", action="store_true",
                       help="Run once and exit")

    args = parser.parse_args()

    agent = MyNewAgent()

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
```

### 2. Add Configuration

Add your agent's configuration to `config.py`:

```python
# Add to config.py
MY_AGENT_INDEX = int(os.getenv("MY_AGENT_INDEX", "3"))  # Next available index
MY_AGENT_MODEL = os.getenv("MY_AGENT_MODEL", "your-model-name")

# Update __all__ list
__all__ = [
    # ... existing entries ...
    "MY_AGENT_INDEX",
    "MY_AGENT_MODEL",
]
```

Also add the environment variables to `.env.example`:
```bash
MY_AGENT_INDEX=3
MY_AGENT_MODEL=your-model-name-or-path
```

### 3. Register Agent with API Server

The API server needs to know about your agent. Update the API server configuration (typically in `api-server.py` or related configuration):

- Add your agent ID to the list of available agents
- Ensure the API can route tasks to your agent

### 4. Update Streamlit UI Integration

If your agent needs UI interaction, update `streamlit-app.py`:

**a. Import your agent index:**
```python
from config import API_URL, UI_AGENT_INDEX, DB_AGENT_INDEX, DT_AGENT_INDEX, MY_AGENT_INDEX
```

**b. Add UI elements in the appropriate tab or section:**
```python
def setup_my_agent_tab():
    """Setup UI for my new agent"""
    conv_idx = 0  # Or manage multiple conversations as needed
    
    # Initialize conversation if needed
    if st.session_state.conversations[MY_AGENT_INDEX][conv_idx] is None:
        st.session_state.conversations[MY_AGENT_INDEX][conv_idx] = create_new_conversation(
            st.session_state.session_id, 
            MY_AGENT_INDEX, 
            system_prompts.MY_AGENT,  # Add your system prompt
            conv_idx
        )
    
    # Display conversation
    load_conversation(
        st.session_state.conversations[MY_AGENT_INDEX][conv_idx], 
        MY_AGENT_INDEX, 
        conv_idx
    )
    
    # Chat input
    if prompt := st.chat_input("Ask the agent..."):
        add_message_to_conversation(
            st.session_state.conversations[MY_AGENT_INDEX][conv_idx],
            "user",
            prompt
        )
        submit_chat_to_agent(
            MY_AGENT_INDEX, 
            conv_idx, 
            st.session_state.conversations[MY_AGENT_INDEX][conv_idx], 
            {"max_tokens": 1000}
        )
```

**c. Add task processor (if needed):**
```python
def process_incoming_task(task):
    result = task.get("result", "")
    agent_id = task["agent_id"]
    conv_idx = task["conv_idx"]
    st.session_state.waiting_for_agent[agent_id][conv_idx] = False
    
    # Add your agent's processor
    if agent_id == MY_AGENT_INDEX:
        process_my_agent_task(result)
    # ... rest of the function
```

### 5. Add System Prompts

Create a system prompt for your agent in `prompts/system.py`:

```python
# Add to prompts/system.py
MY_AGENT = """You are a specialized assistant for [purpose].
Your role is to help users with [specific tasks].
Be helpful, accurate, and concise in your responses.
"""
```

### 6. Deploy to Cluster

**Option A: Via Git (Recommended)**
```bash
# Add and commit your changes locally
git add src/digital_twin_builder/agents/my_new_agent.py
git add src/digital_twin_builder/config.py
git commit -m "Add new agent: MyNewAgent"
git push

# On the cluster, pull the changes
cd /path/to/DigitalTwinBuilder
git pull
```

**Option B: Direct Editing on Cluster**
If you need to edit files directly on the cluster:
```bash
# SSH into the cluster
ssh user@cluster-ip

# Edit files using neovim
nvim /path/to/DigitalTwinBuilder/src/digital_twin_builder/agents/my_new_agent.py
```

### 7. Start the Agent

Run your agent on the cluster or local machine:

```bash
# Run directly
python -m digital_twin_builder.agents.my_new_agent

# Or with parameters
python -m digital_twin_builder.agents.my_new_agent --poll-interval 2.0 --model "your-model-path"

# Test run (process one task and exit)
python -m digital_twin_builder.agents.my_new_agent --once
```

Or add it to the agent starter in `agents_starter.py`:
```python
from agents import UserInteractionAgent, DatabaseAgent, DigitalTwinAgent, MyNewAgent

def start_agents(api_url=None):
    if api_url is None:
        api_url = API_URL
    ui_agent = UserInteractionAgent(UI_AGENT_INDEX, api_url)
    db_agent = DatabaseAgent(DB_AGENT_INDEX, api_url)
    dt_agent = DigitalTwinAgent(DT_AGENT_INDEX, api_url)
    my_agent = MyNewAgent(MY_AGENT_INDEX, api_url)  # Add your agent
```

### Key Points to Remember

- **Agent Index**: Each agent must have a unique index (0, 1, 2, 3, etc.)
- **Conversation Index**: Use `conv_idx` to manage multiple parallel conversations with the same agent
- **BaseAgent Methods**: Use `get_conversation_context()` and `add_to_conversation()` for conversation management
- **Error Handling**: Always handle exceptions in `process_task` and log errors appropriately
- **Model Loading**: Models can be loaded from HuggingFace or local paths; HuggingFace paths sometimes don't work reliably
- **Testing**: Use the `--once` flag to test your agent with a single task before running it continuously



