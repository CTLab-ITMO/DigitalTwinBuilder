from digital_twin_builder.DTlibrary.agents.base_agent import BaseAgent
from digital_twin_builder.DTlibrary.langgraph_flow import build_digital_twin_graph, TwinState
import json

class UserInteractionAgent(BaseAgent):
    """
    UI-адаптер для LangGraph.
    """
    def __init__(self):
        super().__init__("UserInteractionAgent")
        self.graph = build_digital_twin_graph()
        self.state: TwinState = {
            "raw_user_inputs": [],
            "requirements": {},
            "missing_fields": [],
            "interview_finished": False,
            "last_question": None,
            "db_schema": None, 
            "twin_config": None 
        }

    def run(self):
        return "Опишите объект и задачи цифрового двойника в удобной форме."

    def next_step(self, user_text: str):
        self.state["raw_user_inputs"].append(user_text)
        try:
            result = self.graph.invoke(self.state)
            self.state = result
        except Exception as e:
            self.log(f"Ошибка при вызове LangGraph: {e}", "error")
            return f"Произошла ошибка: {e}"

        if not result.get("interview_finished") and result.get("last_question"):
            return result["last_question"]

        return None

    def is_finished(self):
        finished = self.state.get("interview_finished", False)
        return finished

    def get_final_requirements(self):
        return self.state.get("requirements", {})

    def set_db_schema(self, schema: dict):
        self.state["db_schema"] = schema

    def get_db_schema(self):
        return self.state.get("db_schema")

    def set_twin_config(self, config: dict):
        self.state["twin_config"] = config

    def get_twin_config(self):
        return self.state.get("twin_config")