
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from digital_twin_builder.DTlibrary.agents.database_agent import DatabaseAgent
from digital_twin_builder.DTlibrary.agents.digital_twin_agent import DigitalTwinAgent
from digital_twin_builder.DTlibrary.llm import llm_service

class TwinState(TypedDict):
    raw_user_inputs: List[str]
    requirements: Dict[str, Any]
    missing_fields: List[str]
    interview_finished: bool
    last_question: Optional[str]
    db_schema: Optional[Dict[str, Any]]
    twin_config: Optional[Dict[str, Any]] 
    simulation_code: Optional[str] 

INTERVIEW_SYSTEM_PROMPT = """
Ты — инженер по цифровым двойникам промышленного производства.
Твоя задача:
извлекать СТРУКТУРИРОВАННЫЕ требования из свободного текста.
Целевая структура:
{
"object": {
"type": "",
"equipment": [],
"processes": []
},
"goals": [],
"data_sources": {
"sensors": [],
"systems": []
},
"update_requirements": {
"real_time": false,
"frequency": ""
},
"storage": {
"history_days": null,
"aggregation": ""
},
"integrations": [],
"security": {
"criticality": "",
"access_levels": []
}
}
ПРАВИЛА:
- НЕ задавай вопросов
- НЕ добавляй пояснений
- Верни ТОЛЬКО JSON, БЕЗ маркеров кода (без ```json и ```)
- Не используй комментарии или пояснения
"""

def interview_node(state: TwinState) -> TwinState:
    prompt = f"""
ИСТОРИЯ ПОЛЬЗОВАТЕЛЯ:
{state["raw_user_inputs"]}
ТЕКУЩИЕ ТРЕБОВАНИЯ:
{state.get("requirements", {})}
Обнови и дополни требования.
"""
    try:
        generated = llm_service.generate_json(prompt, INTERVIEW_SYSTEM_PROMPT)
        new_reqs = state.get("requirements", {})
        if isinstance(generated, dict):
            for key, value in generated.items():
                if isinstance(value, dict) and isinstance(new_reqs.get(key), dict):
                    new_reqs[key].update(value)
                else:
                    new_reqs[key] = value
        else:
            print(f"Warning: Generated requirements are not a dict: {generated}")
        state["requirements"] = new_reqs
    except Exception as e:
        print(f"Error in interview_node: {e}")
        pass
    return state

REQUIRED_FIELDS = [
("object", "type"),
("goals",),
("data_sources", "sensors"),
("update_requirements", "frequency"),
]

def check_requirements(state: TwinState) -> TwinState:
    missing = []
    reqs = state.get("requirements", {})
    for path in REQUIRED_FIELDS:
        cur = reqs
        found_missing = False
        for key in path:
            if key not in cur or not cur.get(key):
                missing.append(".".join(path))
                found_missing = True
                break
            cur = cur[key]
        if found_missing:
            continue
    state["missing_fields"] = missing
    state["interview_finished"] = len(missing) == 0
    return state

QUESTION_SYSTEM_PROMPT = """
Ты — инженер по цифровым двойникам.
Задай ОДИН конкретный инженерный вопрос,
чтобы заполнить недостающий параметр.
Без приветствий и пояснений.
"""

def question_node(state: TwinState) -> TwinState:
    if state["missing_fields"]:
        prompt = f"""
Не хватает следующих параметров:
{state["missing_fields"]}
Задай один самый важный вопрос.
"""
        try:
            question = llm_service.generate(prompt, QUESTION_SYSTEM_PROMPT)
            state["last_question"] = question
        except Exception as e:
            print(f"Error in question_node: {e}")
            state["last_question"] = "Пожалуйста, уточните требования."
    else:
        state["last_question"] = None
    return state


def db_node(state: TwinState) -> TwinState:
    db_agent = DatabaseAgent()
    schema = db_agent.run(state["requirements"])
    return {**state, "db_schema": schema}


def simulation_node(state: TwinState) -> TwinState:
    twin_agent = DigitalTwinAgent() 
    
    
    simulation_code = twin_agent.run(state["requirements"], state["db_schema"])
    
    return {**state, "simulation_code": simulation_code}


def build_digital_twin_graph():
    """
    Функция для построения и компиляции графа LangGraph.
    """
    graph = StateGraph(TwinState)

    graph.add_node("interview", interview_node)
    graph.add_node("check", check_requirements)
    graph.add_node("ask", question_node)
    graph.add_node("db", db_node) 
    graph.add_node("simulation", simulation_node) 

    graph.set_entry_point("interview")
    graph.add_edge("interview", "check")
    graph.add_conditional_edges(
        "check",
        lambda s: "done" if s["interview_finished"] else "ask",
        {
            "ask": "ask",
            "done": "db" 
        }
    )
    graph.add_edge("ask", END)
    graph.add_edge("db", "simulation") 
    graph.add_edge("simulation", END) 

    return graph.compile()


