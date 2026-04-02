# streamlit_app.py
import streamlit as st
import time
import json
from logging import config
import queue
import threading
from datetime import datetime

import pandas as pd
import plotly.express as px
from prompts import system as system_prompts
from prompts import user as user_prompts
from config import API_URL, UI_AGENT_INDEX, DB_AGENT_INDEX, DT_AGENT_INDEX
from api_utils import (
    init_session,
    get_session,
    submit_task as api_submit_task,
    add_message_to_conversation as api_add_message_to_conversation,
    get_task_status as api_get_task_status,
    get_agent_status as api_get_agent_status,
    create_new_session as api_create_new_session,
    create_new_conversation as api_create_new_conversation
)

# Configuration
if "response_queue" not in st.session_state:
    st.session_state.response_queue = queue.Queue()

# Initialize API session
requests_session = None


def init_requests_session():
    """Initialize requests session for API calls"""
    global requests_session
    requests_session = init_session()
    return requests_session


# Streamlit wrapper functions that add st.error for UI feedback
def submit_task(agent_id, conv_idx, conversation_id, params):
    """Submit task to API"""
    try:
        result = api_submit_task(agent_id, conversation_id, params, conv_idx=conv_idx)
        if result is None:
            st.error("API Error: Failed to submit task")
        return result
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None


def add_message_to_conversation(conversation_id, role, content):
    try:
        return api_add_message_to_conversation(conversation_id, role, content)
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
    return None


def get_task_status(task_id):
    """Get task status from API"""
    try:
        result = api_get_task_status(task_id)
        if result is None:
            st.error("Failed to get task status")
        return result
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
    return None


def get_agent_status(agent_id):
    """Get agent status from API"""
    try:
        return api_get_agent_status(agent_id)
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
    return {"status": "offline"}


def background_poll_task_result(response_queue, task_id):
    poll = 0
    max_poll = 1200
    while poll < max_poll:
        task = get_task_status(task_id)
        if task and task["status"] == "completed":
            response_queue.put(task)
            break
        else:
            time.sleep(1)
        poll += 1


def create_new_conversation(session_id, agent_id, system_prompt, conv_idx=0):
    """Create a new conversation"""
    conversation_id = api_create_new_conversation(session_id, agent_id, system_prompt, conv_idx)
    if conversation_id:
        st.session_state.conversations[agent_id][conv_idx] = conversation_id
    else:
        st.error(f"Не удалось создать новую беседу с агентом {agent_id}")
    return conversation_id


def create_new_session():
    try:
        session_id = api_create_new_session()
        if session_id is None:
            st.error("Failed to create session")
        return session_id
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None



def load_session(session_id):
    """Load a conversation from API"""
    response = requests_session.get(f"{API_URL}/sessions/{session_id}")
    if response.status_code != 200:
        st.error(
            f"Не удалось загрузить сессию {session_id}, запрос завершился с ошибкой {response.status_code}"
        )
        return

    data = response.json()
    reset_session_state()
    st.session_state.session_id = session_id
    for conv in data["conversations"]:
        agent_id = conv["agent_id"]
        conv_idx = conv.get("conv_idx", 0)
        if agent_id > st.session_state.agent_count:
            difference = agent_id - st.session_state.agent_count
            st.session_state.agent_count = agent_id
            st.session_state.conversations.extend([[None]*st.session_state.max_conversations_per_agent for _ in range(difference)])
            st.session_state.messages.extend([ [[] for _ in range(st.session_state.max_conversations_per_agent) ] for _ in range(difference)])
        st.session_state.conversations[agent_id][conv_idx] = conv["id"]
        load_conversation(conv["id"], agent_id, conv_idx)

    def get_last_assistant_message(messages):
        return next((message['content'] for message in reversed(messages) if message['role'] == 'assistant'), None)

    last_ui_assistant_message = get_last_assistant_message(st.session_state.messages[UI_AGENT_INDEX][0])
    if last_ui_assistant_message is None: return
    process_interview_task(last_ui_assistant_message)

    last_db_assistant_message = get_last_assistant_message(st.session_state.messages[DB_AGENT_INDEX][0])
    if last_db_assistant_message is None: return
    process_database_task(last_db_assistant_message)

    last_dt_conf_assistant_message = get_last_assistant_message(st.session_state.messages[DT_AGENT_INDEX][0])
    if last_dt_conf_assistant_message is None: return
    process_dt_conf_task(last_dt_conf_assistant_message)

    last_dt_sim_assistant_message = get_last_assistant_message(st.session_state.messages[DT_AGENT_INDEX][1])
    if last_dt_sim_assistant_message is None: return
    process_dt_sim_task(last_dt_sim_assistant_message)


def load_conversation(conversation_id, agent_id, conv_idx=0):
    """Load a conversation from API"""
    response = requests_session.get(f"{API_URL}/conversations/{conversation_id}")
    if response.status_code != 200:
        st.error(
            f"Не удалось загрузить беседу {conversation_id}, запрос завершился с ошибкой {response.status_code}"
        )
        return

    data = response.json()
    st.session_state.conversations[agent_id][conv_idx] = conversation_id
    st.session_state.messages[agent_id][conv_idx] = data["messages"]

def submit_chat_to_agent(agent_id, conv_idx, conversation_id, params):
    task_info = submit_task(agent_id, conv_idx, conversation_id, params)
    if task_info:
        task_id = task_info["task_id"]
        st.success(f"Task submitted! ID: {task_id[:8]}...")
        st.session_state.waiting_for_agent[agent_id][conv_idx] = True
        st.session_state.tasks.append(task_id)

        thread = threading.Thread(
            target=background_poll_task_result,
            args=(st.session_state.response_queue, task_id),
            daemon=True,
        )
        thread.start()

        # Show immediate feedback
        st.toast("Task submitted! Polling for response...")

def contains_json(message: str):
    try:
        start = message.find('{')
        end = message.rfind('}')
        json_result = message[start:end+1]
        st.session_state.interview_result = json_result
        json.loads(json_result)
        print("Json in message found")
        return True
    except ValueError:
        print("No json in message found")
        return False

def setup_interview_tab():
    conv_idx = 0
    st.header("Создание цифрового двойника производства")

    if st.session_state.conversations[UI_AGENT_INDEX][conv_idx] is None:
        st.markdown("Пожалуйста, выберите существующий чат или создайте новый")
        return

    load_conversation(st.session_state.conversations[UI_AGENT_INDEX][conv_idx], UI_AGENT_INDEX, conv_idx)
    for message in st.session_state.messages[UI_AGENT_INDEX][conv_idx]:
        if message["role"] == "system":
            continue
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    with st.expander("Parameters"):
        temperature = st.slider("Temperature", 0.0, 2.0, 0.7, 0.1)
        max_tokens = st.number_input("Max Tokens", 100, 10000, 1000)

    user_input = st.chat_input(
        "Введите информацию о вашем производстве...",
        disabled=st.session_state.interview_result is not None
            or st.session_state.waiting_for_agent[UI_AGENT_INDEX][conv_idx],
    )
    if user_input:
        params = {"temperature": temperature, "max_tokens": max_tokens}
        response = add_message_to_conversation(
            st.session_state.conversations[UI_AGENT_INDEX][conv_idx],
            role="user",
            content=user_input,
        )
        if response is not None:
            submit_chat_to_agent(
                UI_AGENT_INDEX, conv_idx, st.session_state.conversations[UI_AGENT_INDEX][conv_idx], params
            )
            st.rerun()
    if st.session_state.interview_result is not None:
        st.success("Интервью завершено, переходите к следующей вкладке")

def setup_database_tab():
    conv_idx = 0
    db_conversation = st.session_state.conversations[DB_AGENT_INDEX][conv_idx]
    st.header("Настройка базы данных")

    if st.session_state.interview_result is None:
        st.warning(
            "Пожалуйста, завершите интервью на вкладке 'Интервью с пользователем'"
        )
        return

    st.subheader("Результат интервью")
    st.json(st.session_state.interview_result)

    if db_conversation is None:
        try:
            db_conversation = st.session_state.conversations[DB_AGENT_INDEX][conv_idx] = create_new_conversation(
                st.session_state.session_id, DB_AGENT_INDEX, system_prompts.DB, conv_idx
            )
            add_message_to_conversation(
                db_conversation,
                "user",
                user_prompts.make_db_prompt(st.session_state.interview_result),
            )
            submit_chat_to_agent(
                DB_AGENT_INDEX, conv_idx, db_conversation, {"max_tokens": 3000}
            )
        except Exception:
            st.error("error in creating conversation")
    elif not st.session_state.waiting_for_agent[DB_AGENT_INDEX][conv_idx] and st.session_state.messages[DB_AGENT_INDEX][conv_idx][-1]['role'] != 'assistant':
        if st.session_state.messages[DB_AGENT_INDEX][conv_idx][-1]['role'] != 'user':
            add_message_to_conversation(
                db_conversation,
                "user",
                user_prompts.make_db_prompt(st.session_state.interview_result),
            )
        submit_chat_to_agent(
            DB_AGENT_INDEX, conv_idx, db_conversation, {"max_tokens": 3000}
        )
    load_conversation(db_conversation, DB_AGENT_INDEX, conv_idx)
    
    if st.session_state.db_schema is None:
        return
    st.subheader("Сгенерированная схема базы данных")
    st.code(st.session_state.db_schema, language="sql")

def dt_generate_config():
    conv_idx = 0
    dt_conversation = st.session_state.conversations[DT_AGENT_INDEX][conv_idx]
    if dt_conversation is None:
        try:
            dt_conversation = st.session_state.conversations[DT_AGENT_INDEX][conv_idx] = create_new_conversation(
                st.session_state.session_id, DT_AGENT_INDEX, system_prompts.GenConf, conv_idx
            )
            prompt = user_prompts.make_gen_conf(
                st.session_state.interview_result,
                st.session_state.db_schema
            )
            add_message_to_conversation(
                dt_conversation, role="user", content=prompt)
            submit_chat_to_agent(
                DT_AGENT_INDEX, conv_idx, dt_conversation, {"max_tokens": 3000})
        except Exception:
            st.error("error in creating conversation")
    elif not st.session_state.waiting_for_agent[DT_AGENT_INDEX][conv_idx] and st.session_state.messages[DT_AGENT_INDEX][conv_idx][-1]['role'] != 'assistant':
        if st.session_state.messages[DT_AGENT_INDEX][conv_idx][-1]['role'] != 'user':
            prompt = user_prompts.make_gen_conf(
                st.session_state.interview_result,
                st.session_state.db_schema
            )
            add_message_to_conversation(
                dt_conversation, role="user", content=prompt)

        submit_chat_to_agent(
            DT_AGENT_INDEX, conv_idx, dt_conversation, {"max_tokens": 3000}
        )
    load_conversation(dt_conversation, DT_AGENT_INDEX, conv_idx)

def dt_generate_simulation():
    conv_idx = 1
    dt_conversation = st.session_state.conversations[DT_AGENT_INDEX][conv_idx]
    if dt_conversation is None:
        try:
            dt_conversation = st.session_state.conversations[DT_AGENT_INDEX][conv_idx] = create_new_conversation(
                st.session_state.session_id, DT_AGENT_INDEX, system_prompts.GenSim, conv_idx
            )
            prompt = user_prompts.make_gen_sim(
                st.session_state.interview_result,
                st.session_state.db_schema
            )
            add_message_to_conversation(
                dt_conversation, role="user", content=prompt)
            submit_chat_to_agent(
                DT_AGENT_INDEX, conv_idx, dt_conversation, {})
        except Exception:
            st.error("error in creating conversation")
    elif not st.session_state.waiting_for_agent[DT_AGENT_INDEX][conv_idx] and st.session_state.messages[DT_AGENT_INDEX][conv_idx][-1]['role'] != 'assistant':
        if st.session_state.messages[DT_AGENT_INDEX][conv_idx][-1]['role'] != 'user':
            prompt = user_prompts.make_gen_sim(
                st.session_state.interview_result,
                st.session_state.db_schema
            )
            add_message_to_conversation(
                dt_conversation, role="user", content=prompt)

        submit_chat_to_agent(
            DT_AGENT_INDEX, conv_idx, dt_conversation, {"max_tokens": 3000}
        )
    load_conversation(dt_conversation, DT_AGENT_INDEX, conv_idx)

def dt_modify_config():
    # TODO: implement
    pass


def setup_twin_tab():
    st.header("Конфигурация цифрового двойника")
        
    if st.session_state.db_schema is None:
        st.warning("⚠️ Пожалуйста, завершите настройку базы данных")
        return
    
    st.subheader("SQL код для БД")
    with st.expander("Просмотр SQL"):
        st.code(st.session_state.db_schema, language="sql")
        
    st.download_button(
        "📥 Скачать SQL",
        st.session_state.db_schema,
        "schema.sql",
        "text/plain",
        key="download_sql"
    )
    
    if st.session_state.twin_config is None:
        if st.button("⚙️ Сгенерировать конфигурацию", key="generate_config_btn"):
            with st.spinner("Генерация конфигурации..."):
                dt_generate_config()
        return
    
    st.subheader("Конфигурация цифрового двойника")
    with st.expander("Посмотреть конфигурацию ЦД"):
        st.json(st.session_state.twin_config, expanded=True)
    
    st.subheader("Код симуляции PyChrono")
    
    if 'simulation_code' not in st.session_state:
        if st.button("🔧 Сгенерировать код", key="generate_sim_btn"):
            with st.spinner("Генерация кода..."):
                dt_generate_simulation()
   
    if 'simulation_code' in st.session_state:
        with st.expander("Просмотр кода PyChrono"):
            st.code(st.session_state.simulation_code, language="python")
        
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "📥 Скачать код",
                st.session_state.simulation_code,
                "simulation.py",
                "text/x-python",
                key="download_sim"
            )
        with col2:
            if st.button("🔄 Перегенерировать", key="regen_sim"):
                del st.session_state.simulation_code
                st.rerun()
    
    
    # st.divider()
    # st.subheader("🚀 Запуск цифрового двойника")
    # 
    # mode = st.radio(
    #     "Режим сенсоров", 
    #     ["Симуляция", "Реальное оборудование"],
    #     key="sensor_mode_radio"
    # )
    # sensor_mode = 'sim' if mode == "Симуляция" else 'real'
    # 
    # col1, col2 = st.columns(2)
    # 
    # with col1:
    #     if st.button("▶️ Запустить", key="start_twin_btn", type="primary"):
    #         try:
    #             self.sensor_manager = SensorManager(mode=sensor_mode)
    #             self.sensor_manager.start()
    #             
    #             self.db_manager = DatabaseManager(
    #                 dbname="digital_twin",
    #                 user="postgres",
    #                 password="omgssmyalg"
    #             )
    #             self.db_manager.create_sensor_tables()
    #             
    #             st.session_state.sensor_running = True
    #             st.session_state.sensor_mode = sensor_mode
    #             st.success("✅ Цифровой двойник запущен!")
    #         except Exception as e:
    #             st.error(f"❌ Ошибка: {str(e)}")
    # 
    # with col2:
    #     if st.button(
    #         "⏹️ Остановить",
    #         disabled=not st.session_state.get('sensor_running', False),
    #         key="stop_twin_btn"
    #     ):
    #         if self.sensor_manager:
    #             self.sensor_manager.stop()
    #         if self.db_manager:
    #             self.db_manager.close()
    #         st.session_state.sensor_running = False
    #         st.success("⏹️ Остановлено")
    # 

def setup_sensor_tab():
    # TODO: implement
    pass

def reset_session_state():
    st.session_state.conversations = [ [None]*st.session_state.max_conversations_per_agent for _ in range(st.session_state.agent_count) ]
    st.session_state.waiting_for_agent = [ [False]*st.session_state.max_conversations_per_agent for _ in range(st.session_state.agent_count) ]
    st.session_state.messages = [ [[] for _ in range(st.session_state.max_conversations_per_agent) ] for _ in range(st.session_state.agent_count) ]
    st.session_state.db_schema = None
    st.session_state.twin_config = None
    st.session_state.interview_result = None
    st.session_state.tasks = []
    st.session_state.temperature_history = []

def init_session_state():
    """Initialize session state for chat"""
    st.session_state.agent_count = 3
    st.session_state.max_conversations_per_agent = 10
    if "db_schema" not in st.session_state:
        st.session_state.db_schema = None
    if "twin_config" not in st.session_state:
        st.session_state.twin_config = None
    if "interview_result" not in st.session_state:
        st.session_state.interview_result = None
    if "conversations" not in st.session_state:
        st.session_state.conversations = [ [None]*st.session_state.max_conversations_per_agent for _ in range(st.session_state.agent_count) ]
    if "waiting_for_agent" not in st.session_state:
        st.session_state.waiting_for_agent = [ [False]*st.session_state.max_conversations_per_agent for _ in range(st.session_state.agent_count) ]
    if "messages" not in st.session_state:
        st.session_state.messages = [ [[] for _ in range(st.session_state.max_conversations_per_agent) ] for _ in range(st.session_state.agent_count) ]
    if "tasks" not in st.session_state:
        st.session_state.tasks = []
    if "temperature_history" not in st.session_state:
        st.session_state.temperature_history = []
    if 'response_queue' not in st.session_state:
        st.session_state.response_queue = queue.Queue()


def process_interview_task(result):
    try:
        start = result.find("{")
        end = result.rfind("}")
        json_result = json.loads(result[start : end + 1])
        if json_result["completed"] == True:
            st.session_state.interview_result = json_result["requirements"]
    except ValueError:
        # NOTE: maybe should resend message
        print("No json in message found")
        st.error(result)

def process_database_task(result):
    st.session_state.db_schema = result
    return
    start = result.find("```sql")
    end = result.rfind("```")
    st.session_state.db_schema = result[start + 6 : end]
    # TODO: better parse for sql

def process_dt_conf_task(result):
    try:
        start = result.find("{")
        end = result.rfind("}")
        json_result = result[start : end + 1]
        st.session_state.twin_config = json.loads(json_result)
    except ValueError:
        # NOTE: maybe should resend message
        print("No json in dt message found")
        st.error(result)

def process_dt_sim_task(result):
    start = result.find("</think>")
    st.session_state.simulation_code = result[start + 8:]

def process_incoming_task(task):
    result = task.get("result", "")
    agent_id = task["agent_id"]
    conv_idx = task["conv_idx"]
    st.session_state.waiting_for_agent[agent_id][conv_idx] = False
    if agent_id == 0:
        process_interview_task(result)
    elif agent_id == 1:
        process_database_task(result)
    elif agent_id == 2:
        print(conv_idx)
        if conv_idx == 0:
            process_dt_conf_task(result)
        elif conv_idx == 1:
            process_dt_sim_task(result)
        else:
            print(f"No task processor defined for agent {agent_id} conversation index {conv_idx}")
    else:
        print(f"No agent with id = {agent_id} defined")

def initialize_ui():
    st.set_page_config(page_title="Digital Twin Builder", layout="wide")
    st.title("Digital Twin Builder🏭")

    init_session_state()

    with st.sidebar:
        st.title("💬 Sessions")

        # Load conversations
        try:
            response = requests_session.get(f"{API_URL}/sessions", params={"user_id": "streamlit_user"})
            if response.status_code == 200:
                st.session_state.sessions = response.json()["sessions"]
        except Exception as e:
            st.error(f"Connection error: {str(e)}")
            return

        # New chat button
        if st.button("➕ New Chat", use_container_width=True):
            session_id = create_new_session()
            load_session(session_id)
            UI_AGENT_INDEX = 0
            conv_idx = 0
            st.session_state.conversations[UI_AGENT_INDEX][conv_idx] = create_new_conversation(
                st.session_state.session_id, UI_AGENT_INDEX, system_prompts.UI, conv_idx=0
            )
            # init message
            add_message_to_conversation(st.session_state.conversations[UI_AGENT_INDEX][conv_idx], "assistant", user_prompts.init_ui_assistant_answer())
            load_conversation(st.session_state.conversations[UI_AGENT_INDEX][conv_idx], UI_AGENT_INDEX, conv_idx)
            st.rerun()
            # submit_chat_to_agent(UI_AGENT_INDEX, conv_idx, st.session_state.conversations[UI_AGENT_INDEX][conv_idx], {})

        st.divider()

        # list conversations
        for session in st.session_state.sessions:
            title = session.get("title", f"chat {session['id'][:8]}")
            if st.button(title, key=session["id"], use_container_width=True):
                load_session(session["id"])

        st.header("agent status")

        for agent_id in range(0, st.session_state.agent_count):
            status = get_agent_status(agent_id)
            status_color = {"idle": "🟢", "busy": "🟡", "offline": "🔴"}.get(
                status.get("status", "offline"), "⚪"
            )

            st.markdown(f"**agent {agent_id}** {status_color}")
            caption_str = f"status: {status.get('status', 'offline')}"
            try:
                response = requests_session.get(f"{API_URL}/queue/{agent_id}", timeout=5)
                if response.status_code == 200:
                    queue = response.json()
                    caption_str += f", pending {queue["pending_count"]}"
                    if queue["active_task"]:
                        caption_str += f", active: {queue['active_task']['id'][:8]}..."
            except Exception as e:
                st.error(f"Connection error: {str(e)}")

            st.caption(caption_str)

    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "интервью с пользователем",
            "создание базы данных",
            "цифровой двойник",
            "обзор графиков датчиков",
        ]
    )

    with tab1:
        setup_interview_tab()
    with tab2:
        setup_database_tab()
    with tab3:
        setup_twin_tab()
    with tab4:
        setup_sensor_tab()

    while not st.session_state.response_queue.empty():
        task = st.session_state.response_queue.get()
        process_incoming_task(task)
        st.rerun()

    # rerun every 10 seconds
    time.sleep(10)
    st.rerun()

def main():
    global requests_session
    requests_session = init_requests_session()
    initialize_ui()


if __name__ == "__main__":
    main()
