# streamlit_app.py
import json
from logging import config
import queue
import threading
import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
import prompts

# Configuration
API_URL = "http://localhost:8000"  # Change to your API URL
if "response_queue" not in st.session_state:
    st.session_state.response_queue = queue.Queue()


# Helper functions
def submit_task(agent_id, conversation_id, params):
    """Submit task to API"""
    try:
        response = requests.post(
            f"{API_URL}/tasks",
            json={
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "params": params,
                "priority": 5,
            },
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"API Error: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None


def add_message_to_conversation(conversation_id, role, content):
    try:
        response = requests.post(
            f"{API_URL}/conversations/{conversation_id}/messages",
            params={
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
            },
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"API Error: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None


def get_task_status(task_id):
    """Get task status from API"""
    try:
        response = requests.get(f"{API_URL}/tasks/{task_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None


def get_agent_status(agent_id):
    """Get agent status from API"""
    try:
        response = requests.get(f"{API_URL}/agents/{agent_id}/status", timeout=5)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return {"status": "offline"}


def background_poll_task_result(response_queue, task_id):
    poll = 0
    max_poll = 100
    while poll < max_poll:
        task = get_task_status(task_id)
        if task and task["status"] == "completed":
            response_queue.put(task)
            break
        else:
            time.sleep(1)
        poll += 1


def create_new_conversation(session_id, agent_id, system_prompt):
    """Create a new conversation"""
    response = requests.post(
        f"{API_URL}/conversations",
        params={"session_id": session_id, "agent_id": agent_id, "conv_idx": conv_idx},
    )
    if response.status_code == 200:
        conversation_id = response.json()["conversation_id"]
        st.session_state.conversations[agent_id - 1][conv_idx] = conversation_id
    else:
        st.error(
            f"Не удалось создать новую беседу с агентом {agent_id}, запрос завершился с ошибкой {response.status_code}"
        )
        return None
    response_message = add_message_to_conversation(
        conversation_id, "system", system_prompt
    )
    if response_message is not None:
        return conversation_id
    else:
        st.error(
            f"Не удалось добавить системный промпт в новую беседу {conversation_id} с агентом {agent_id}"
        )
        return None


def create_new_session():
    response = requests.post(
        f"{API_URL}/sessions", params={"user_id": "streamlit_user", "title": "New Chat"}
    )
    if response.status_code == 200:
        session_id = response.json()["session_id"]
        return session_id
    else:
        st.error(
            f"Не удалось создать новую сессию, запрос завершился с ошибкой {response.status_code}"
        )
        return None


def load_session(session_id):
    """Load a conversation from API"""
    response = requests.get(f"{API_URL}/sessions/{session_id}")
    if response.status_code != 200:
        st.error(
            f"Не удалось загрузить сессию {session_id}, запрос завершился с ошибкой {response.status_code}"
        )
        return

    data = response.json()
    st.session_state.session_id = session_id
    for conv in data["conversations"]:
        agent_id = conv["agent_id"]
        conv_idx = conv.get("conv_idx", 0)
        if agent_id > st.session_state.agent_count:
            difference = agent_id - st.session_state.agent_count
            st.session_state.agent_count = agent_id
            st.session_state.conversations.extend([[None]*st.session_state.max_conversations_per_agent for _ in range(difference)])
            st.session_state.messages.extend([ [[] for _ in range(st.session_state.max_conversations_per_agent) ] for _ in range(difference)])
        st.session_state.conversations[agent_id - 1][conv_idx] = conv["id"]


def load_conversation(conversation_id, agent_id):
    """Load a conversation from API"""
    response = requests.get(f"{API_URL}/conversations/{conversation_id}")
    if response.status_code != 200:
        st.error(
            f"Не удалось загрузить беседу {conversation_id}, запрос завершился с ошибкой {response.status_code}"
        )
        return

    data = response.json()
    st.session_state.conversations[agent_id - 1][conv_idx] = conversation_id
    st.session_state.messages[agent_id - 1][conv_idx] = data["messages"]


def submit_chat_to_agent(agent_id, conversation_id, params):
    task_info = submit_task(agent_id, conversation_id, params)
    if task_info:
        task_id = task_info["task_id"]
        st.success(f"Task submitted! ID: {task_id[:8]}...")
        st.session_state.tasks.append(task_id)

        thread = threading.Thread(
            target=background_poll_task_result,
            args=(st.session_state.response_queue, task_id),
            daemon=True,
        )
        thread.start()

        # Show immediate feedback
        st.toast("Task submitted! Polling for response...")


def setup_interview_tab():
    ui_agent_id = 1
    conv_idx = 0
    st.header("Создание цифрового двойника производства")

    if st.session_state.conversations[ui_agent_id - 1][conv_idx] is None:
        st.markdown("Пожалуйста, выберите существующий чат или создайте новый")
        return

    load_conversation(st.session_state.conversations[ui_agent_id - 1][conv_idx], ui_agent_id, conv_idx)
    for message in st.session_state.messages[ui_agent_id - 1][conv_idx]:
        if message["role"] == "system":
            continue
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    with st.expander("Parameters"):
        temperature = st.slider("Temperature", 0.0, 2.0, 0.7, 0.1)
        max_tokens = st.number_input("Max Tokens", 100, 4000, 1000)

    user_input = st.chat_input(
        "Введите информацию о вашем производстве...",
        disabled=st.session_state.get("interview_completed", False)
        or not st.session_state.response_queue.empty(),
    )
    if user_input:
        params = {"temperature": temperature, "max_tokens": max_tokens}
        response = add_message_to_conversation(
            st.session_state.conversations[ui_agent_id - 1],
            role="user",
            content=user_input,
        )
        if response is not None:
            submit_chat_to_agent(
                ui_agent_id, st.session_state.conversations[ui_agent_id - 1], params
            )
            st.rerun()
    if st.session_state.get("interview_completed", False):
        st.success("Интервью завершено, переходите к следующей вкладке")


def setup_database_tab():
    db_agent_id = 2
    conv_idx = 0
    st.header("Настройка базы данных")

    if not st.session_state.get("interview_completed", False):
        st.warning(
            "Пожалуйста, завершите интервью на вкладке 'Интервью с пользователем'"
        )
        return

    st.subheader("Результат интервью")
    st.json(st.session_state.interview_result)

    if st.session_state.conversations[db_agent_id - 1][conv_idx] is None:
        st.session_state.conversations[db_agent_id - 1][conv_idx] = create_new_conversation(
            st.session_state.session_id, db_agent_id, prompts.system.DB, conv_idx
        )
        add_message_to_conversation(
            st.session_state.conversations[db_agent_id - 1][conv_idx],
            "user",
            prompts.user.make_db(st.session_state.interview_result),
        )
        submit_chat_to_agent(
            db_agent_id, st.session_state.conversations[db_agent_id - 1][conv_idx], {}
        )
    load_conversation(st.session_state.conversations[db_agent_id - 1][conv_idx], db_agent_id, conv_idx)

    if "db_json" in st.session_state:
        st.subheader("Сгенерированная схема базы данных")
        st.json(st.session_state.db_json)

def dt_generate_config():
    try:
        # TODO: 2d array for conversations and messages
        prompt = prompts.user.make_config(
            st.session_state.interview_result,
            st.session_state.db_schema
        )
        add_message_to_conversation(
            st.session_state.conversations[2], role="user", content=prompt)
        submit_chat_to_agent(
            3, st.session_state.conversations[2], {})
        st.rerun()
    except Exception as e:
        st.error(f"Ошибка: {str(e)}")

def dt_generate_simulation():
    try:
        # TODO: 2d array for conversations and messages
        prompt = prompts.user.make_simulation(
            st.session_state.interview_result,
            st.session_state.db_schema,
            st.session_state.twin_config
        )
        add_message_to_conversation(
            st.session_state.conversations[2], role="user", content=prompt)
        submit_chat_to_agent(
            3, st.session_state.conversations[2], {})
        st.rerun()
    except Exception as e:
        st.error(f"Ошибка: {str(e)}")

def dt_generate_db_schema():
    try:
        # TODO: 2d array for conversations and messages
        prompt = prompts.user.make_db_schema(
            st.session_state.interview_result,
            st.session_state.db_schema
        )
        add_message_to_conversation(
            st.session_state.conversations[2], role="user", content=prompt)
        submit_chat_to_agent(
            3, st.session_state.conversations[2], {})
        st.rerun()
    except Exception as e:
        st.error(f"Ошибка: {str(e)}")

def dt_modify_config():
    # TODO: implement
    pass


def setup_twin_tab():
    dt_agent_id = 3
    st.header("Конфигурация цифрового двойника")
        
    if 'db_json' not in st.session_state:
        st.warning("⚠️ Пожалуйста, завершите настройку базы данных")
        return
    
    st.subheader("Схема базы данных")
    with st.expander("Посмотреть схему БД"):
        st.json(st.session_state.db_schema)
    
    if 'twin_config' not in st.session_state:
        if st.button("⚙️ Сгенерировать конфигурацию", key="generate_config_btn"):
            with st.spinner("Генерация конфигурации..."):
                dt_generate_config()
        return
    
    st.subheader("Конфигурация цифрового двойника")
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
    
    st.subheader("SQL код для БД")
    
    if 'database_code' not in st.session_state:
        if st.button("🗄️ Сгенерировать SQL", key="generate_sql_btn"):
            with st.spinner("Генерация SQL..."):
                dt_generate_db_schema()
    
    if 'database_code' in st.session_state:
        with st.expander("Просмотр SQL"):
            st.code(st.session_state.database_code, language="sql")
        
        st.download_button(
            "📥 Скачать SQL",
            st.session_state.database_code,
            "schema.sql",
            "text/plain",
            key="download_sql"
        )
    
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


def init_session_state():
    """Initialize session state for chat"""
    st.session_state.agent_count = 3
    st.session_state.max_conversations_per_agent = 10
    if "conversations" not in st.session_state:
        st.session_state.conversations = [ [None]*st.session_state.max_conversations_per_agent for _ in range(st.session_state.agent_count) ]
    if "messages" not in st.session_state:
        st.session_state.messages = [ [[] for _ in range(st.session_state.max_conversations_per_agent) ] for _ in range(st.session_state.agent_count) ]
    if "tasks" not in st.session_state:
        st.session_state.tasks = []
    if "temperature_history" not in st.session_state:
        st.session_state.temperature_history = []


def process_incoming_task(task):
    result = task.get("result", "")
    agent_id = task["agent_id"]
    if agent_id == 1:
        # if json then it is final answer
        try:
            start = result.find("{")
            end = result.rfind("}")
            json_result = result[start : end + 1]
            st.session_state.interview_result = json.loads(json_result)
            print("Json in message found")
        except ValueError:
            print("No json in message found")
            return
        st.session_state.interview_completed = True
    elif agent_id == 2:
        try:
            start = result.find("{")
            end = result.rfind("}")
            json_result = result[start : end + 1]
            st.session_state.db_json = json.loads(json_result)
            print("Json in message found")
        except ValueError:
            print("No json in message found")
            return -1
    elif agent_id == 3:
        pass
    else:
        print(f"No agent with id = {agent_id} defined")

def initialize_ui():
    st.set_page_config(page_title="Digital Twin Builder", layout="wide")
    st.title("Digital Twin Builder🏭")

    init_session_state()

    with st.sidebar:
        st.title("💬 Sessions")

        # Load conversations
        response = requests.get(
            f"{API_URL}/sessions", params={"user_id": "streamlit_user"}
        )
        if response.status_code == 200:
            st.session_state.sessions = response.json()["sessions"]

        # New chat button
        if st.button("➕ New Chat", use_container_width=True):
            session_id = create_new_session()
            load_session(session_id)
            st.session_state.conversations[0] = create_new_conversation(
                st.session_state.session_id, 1, prompts.system.UI
            )
            submit_chat_to_agent(1, st.session_state.conversations[0], {})

        st.divider()

        # list conversations
        for session in st.session_state.sessions:
            title = session.get("title", f"chat {session['id'][:8]}")
            if st.button(title, key=session["id"], use_container_width=True):
                load_session(session["id"])

        st.header("agent status")

        for agent_id in range(1, st.session_state.agent_count + 1):
            status = get_agent_status(agent_id)
            status_color = {"idle": "🟢", "busy": "🟡", "offline": "🔴"}.get(
                status.get("status", "offline"), "⚪"
            )

            st.markdown(f"**agent {agent_id}** {status_color}")
            caption_str = f"status: {status.get('status', 'offline')}"

            response = requests.get(f"{API_URL}/queue/{agent_id}", timeout=5)
            if response.status_code == 200:
                queue = response.json()
                caption_str += f", pending {queue['pending_count']}"
                if queue["active_task"]:
                    caption_str += f", active: {queue['active_task']['id'][:8]}..."
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

    time.sleep(10)
    st.rerun()


def main():
    initialize_ui()


if __name__ == "__main__":
    main()
