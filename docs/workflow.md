# System workflow
> **_NOTE:_**  If you want access either to the server or cluster, send me your public ssh key on tg: [@gozebone](https://t.me/gozebone)
## How distributed system works
There are 3 components to the system:
- Cluster with agents
- Server with database and api
- Locally ran streamlit control panel (could also be on server) 

Cluster and Streamlit are sending http requests to api, in simple terms streamlit adds tasks and agent on cluster completes task and sends an answer.

### Example of full communication workflow:
Streamlit side sending request to the agent:
```python
agent_id = 1 # some number from 1...N
st.session_state.conversations[agent_id - 1] = create_new_conversation(
            st.session_state.session_id, agent_id, prompts.system.example_agent_prompt
        )
response = add_message_to_conversation(
    st.session_state.conversations[agent_id - 1],
    role="user",
    content=prompts.user.example_make_agent_prompt(user_input),
)
if response is not None:
    submit_chat_to_agent(
        ui_agent_id, st.session_state.conversations[ui_agent_id - 1], params
    ) 
```
> **_NOTE:_**  Right now as you can see, agent ids are starting from one. Fell free to change that, so agent ids are starting with zero.

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
        params = task.get("params", {})
        task_id = task["task_id"][:8]

        self.logger.info(f"Processing task {task_id}")
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
    process_incoming_task(task)
```
For more implementation details please see [streamlit-app.py](src/digital_twin_builder/streamlit-app.py), [prompts/](src/digital_twin_builder/prompts/), [agents/](src/digital_twin_builder/DTlibrary/agents/)

## How to add new agent
To add agent you need to add agent file to cluster. The best way to do this is to write it locally and push it to github and then pull on cluster. But if for watever reason you can't do that, you can use neovim to edit files on cluster directly.



