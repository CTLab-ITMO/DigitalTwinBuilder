# streamlit_app.py
import streamlit as st
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import json
import threading
import queue
from datetime import datetime
from prompts import system as sys_prompts
from DTlibrary.cores.sensor_manager import SensorManager
from DTlibrary.cores.database import DatabaseManager
import pandas as pd
import plotly.express as px

# Configuration
API_URL = "http://188.119.67.226:8000"  # Change to your API URL
requests_session = None

# Helper functions
def submit_task(agent_id, conversation_id, params):
    """Submit task to API"""
    try:
        response = requests_session.post(
            f"{API_URL}/tasks",
            json={
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "params": params,
                "priority": 5
            },
            timeout=10
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
        response = requests_session.post(
            f"{API_URL}/conversations/{conversation_id}/messages", 
            params={
                "conversation_id": conversation_id,
                "role": role,
                "content": content},
            timeout=10)
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
        response = requests_session.get(f"{API_URL}/tasks/{task_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
    return None

def get_agent_status(agent_id):
    """Get agent status from API"""
    try:
        response = requests_session.get(f"{API_URL}/agents/{agent_id}/status", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
    return {"status": "offline"}

def background_poll_task_result(response_queue, task_id):
    poll = 0
    max_poll = 100
    while (poll < max_poll):
        task = get_task_status(task_id)
        if task and task["status"] == "completed":
            response_queue.put(task)
            break
        else: 
            time.sleep(1)
        poll += 1


def create_new_conversation(session_id, agent_id, system_prompt, metadata = {}):
    """Create a new conversation"""
    try:
        response = requests_session.post(
            f"{API_URL}/conversations",
            params={"session_id": session_id, "agent_id": agent_id}
        )
        if response.status_code == 200:
            conversation_id = response.json()["conversation_id"]
        else:
            st.error(f"Не удалось создать новую беседу с агентом {agent_id}, запрос завершился с ошибкой {response.status_code}")
            return None
        response_message = add_message_to_conversation(conversation_id, "system", system_prompt)
        if response_message is not None:
            return conversation_id
        else:
            st.error(f"Не удалось добавить системный промпт в новую беседу {conversation_id} с агентом {agent_id}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
    return None

def create_new_session():
    try:
        response = requests_session.post(
            f"{API_URL}/sessions",
            params={"user_id": "streamlit_user", "title": "New Chat"}
        )
        if response.status_code == 200:
            session_id = response.json()["session_id"]
            return session_id
        else:
            st.error(f"Не удалось создать новую сессию, запрос завершился с ошибкой {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
    return None
    
def load_session(session_id):
    """Load a conversation from API"""
    try:
        response = requests_session.get(f"{API_URL}/sessions/{session_id}")
        if response.status_code != 200:
            st.error(f"Не удалось загрузить сессию {session_id}, запрос завершился с ошибкой {response.status_code}")
            return

        data = response.json()
        st.session_state.session_id = session_id
        for conv in data["conversations"]:
            agent_id = conv["agent_id"]
            if agent_id > st.session_state.agent_count:
                difference = agent_id - st.session_state.agent_count
                st.session_state.agent_count = agent_id
                st.session_state.conversations.extend([None] * difference)
            st.session_state.conversations[agent_id - 1] = conv["id"]
    except Exception as e:
        st.error(f"Connection error: {str(e)}")

def load_conversation(conversation_id, agent_id):
    """Load a conversation from API"""
    try:
        response = requests_session.get(f"{API_URL}/conversations/{conversation_id}")
        if response.status_code != 200:
            st.error(f"Не удалось загрузить беседу {conversation_id}, запрос завершился с ошибкой {response.status_code}")
            return 

        data = response.json()
        st.session_state.conversations[agent_id - 1] = conversation_id
        st.session_state.messages[agent_id - 1] = data["messages"]
    except Exception as e:
        st.error(f"Connection error: {str(e)}")

def submit_chat_to_agent(agent_id, conversation_id, params):
    task_info = submit_task(agent_id, conversation_id, params)
    if task_info:
        task_id = task_info['task_id']
        st.success(f"Task submitted! ID: {task_id[:8]}...")
        st.session_state.tasks.append(task_id)

        thread = threading.Thread(
            target=background_poll_task_result,
            args=(st.session_state.response_queue, task_id),
            daemon=True
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
    ui_agent_id = 1
    st.header("Создание цифрового двойника производства")
    
    if st.session_state.conversations[ui_agent_id - 1] is None:
        st.markdown("Пожалуйста, выберите существующий чат или создайте новый")
        return

    load_conversation(st.session_state.conversations[ui_agent_id - 1], ui_agent_id)

    if (contains_json(st.session_state.messages[0][-1]["content"])):
        st.session_state.interview_completed = True

    for message in st.session_state.messages[ui_agent_id - 1]:
        if message["role"] == "system":
            continue
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    
    with st.expander("Parameters"):
        temperature = st.slider("Temperature", 0.0, 2.0, 0.7, 0.1)
        max_tokens = st.number_input("Max Tokens", 100, 4000, 1000)

    user_input = st.chat_input("Введите информацию о вашем производстве...", 
                               disabled=
                                    st.session_state.get('interview_completed', False) or 
                                    not st.session_state.response_queue.empty())
    if user_input:
        params = {
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        response = add_message_to_conversation(st.session_state.conversations[ui_agent_id - 1], role="user", content=user_input)
        if response is not None:
            submit_chat_to_agent(ui_agent_id, st.session_state.conversations[ui_agent_id - 1], params)
            st.rerun()
    if st.session_state.get('interview_completed', False):
        st.success("Интервью завершено, переходите к следующей вкладке")


def setup_database_tab():
    db_agent_id = 2
    st.header("Настройка базы данных")
    
    if not st.session_state.get('interview_completed', False):
        st.warning("Пожалуйста, завершите интервью на вкладке 'Интервью с пользователем'")
        return

    st.subheader("Результат интервью")
    st.json(st.session_state.interview_result)

    if st.session_state.conversations[db_agent_id - 1] is None:
        st.session_state.conversations[db_agent_id - 1] = create_new_conversation(st.session_state.session_id, db_agent_id, sys_prompts.DB)    
        add_message_to_conversation(st.session_state.conversations[db_agent_id - 1], "user", st.session_state.interview_result)
        submit_chat_to_agent(db_agent_id, st.session_state.conversations[db_agent_id - 1], {})
    load_conversation(st.session_state.conversations[db_agent_id - 1], db_agent_id)
    
    if ("db_schema" in st.session_state):
        st.subheader("Сгенерированная схема базы данных")
        st.markdown(f"```{st.session_state.db_schema}```")

def setup_twin_tab():
    dt_agent_id = 3
    st.header("Конфигурация цифрового двойника")
  
    if 'db_schema' not in st.session_state:
        st.warning("Пожалуйста, настройте базу данных на предыдущей вкладке")
        return

    if st.session_state.conversations[dt_agent_id - 1] is None:
        st.session_state.conversations[dt_agent_id - 1] = create_new_conversation(st.session_state.session_id, dt_agent_id, sys_prompts.DT)
        # TODO: check context is right for dt agetn
        add_message_to_conversation(st.session_state.conversations[dt_agent_id  - 1], "user", st.session_state.interview_result)
        add_message_to_conversation(st.session_state.conversations[dt_agent_id  - 1], "user", st.session_state.db_schema)

        submit_chat_to_agent(dt_agent_id, st.session_state.conversations[dt_agent_id  - 1], {})

    if ("dt_config" in st.session_state):
        st.subgeader("Итоговая конфигурация двойника")
        st.json(st.session_state.dt_config)

    if st.button("Запустить цифровой двойник"):
        try:
            st.session_state.sensor_manager = SensorManager(mode='sim')
            st.session_state.sensor_manager.start()

            st.session_state.db_manager = DatabaseManager()
            start = st.session_state.db_schema.find("INSERT")
            end = st.session_state.db_schema.rfind(";")
            st.session_state.db_manager.execute(st.session_state.db_schema[start:end + 1])
            st.session_state.sensor_running = True
            st.success("Цифровой двойник успешно запущен!")
        except Exception as e:
            st.error(f"Ошибка запуска: {str(e)}")
#     
#     if st.button("Остановить", disabled=not st.session_state.get('sensor_running', False)):
#         .sensor_manager.stop()
#         if .db_manager:
#             .db_manager.close()
#         st.session_state.sensor_running = False
#         st.success("Работа цифрового двойника остановлена")

def setup_sensor_tab():
    st.header("Мониторинг производства")
    
    if not st.session_state.get('sensor_running', False):
        st.warning("Цифровой двойник не запущен")
        return
    
    data = st.session_state.sensor_manager.get_data()
    if data:
        print(data)
        display_sensor_data(data)

def display_sensor_data(data):
    st.subheader("Текущие показания")

    sensor_data = data["sensor_data"]
    display_data = []

    for param, value in sensor_data.items():
        display_data.append({
            "Параметр": param,
            "Значение": value,
            "Время": datetime.fromtimestamp(data["timestamp"])
        })

    st.dataframe(pd.DataFrame(display_data))
    plot_sensor_data(data)

def plot_sensor_data(data):
    col1, col2 = st.columns(2)

    with col1:
        st.session_state.temperature_history.append({
            "timestamp": datetime.fromtimestamp(data["timestamp"]),
            "value": data["sensor_data"].get("temperature", 0)
        })
        temp_df = pd.DataFrame(st.session_state.temperature_history[-100:])
        fig_temp = px.line(temp_df, x="timestamp", y="value", title="Температура")
        st.plotly_chart(fig_temp, use_container_width=True)

def init_session_state():
    """Initialize session state for chat"""
    st.session_state.agent_count = 3
    if 'sessions' not in st.session_state:
        st.session_state.sessions = []
    if 'conversations' not in st.session_state:
        st.session_state.conversations = [None] * st.session_state.agent_count
    if 'messages' not in st.session_state:
        st.session_state.messages = [[]] * st.session_state.agent_count
    if 'tasks' not in st.session_state:
        st.session_state.tasks = []
    if 'temperature_history' not in st.session_state:
        st.session_state.temperature_history = []
    if 'response_queue' not in st.session_state:
        st.session_state.response_queue = queue.Queue()


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

        # New chat button
        if st.button("➕ New Chat", use_container_width=True):
            session_id = create_new_session()
            load_session(session_id)
            st.session_state.conversations[0] = create_new_conversation(st.session_state.session_id, 1, sys_prompts.UI)
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
            status_color = {
                "idle": "🟢",
                "busy": "🟡",
                "offline": "🔴"
            }.get(status.get("status", "offline"), "⚪")
            
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

    tab1, tab2, tab3, tab4 = st.tabs([
        "интервью с пользователем", 
        "создание базы данных", 
        "цифровой двойник",
        "обзор графиков датчиков"
    ])
        
    with tab1:
        setup_interview_tab()
    with tab2:
        setup_database_tab()
    with tab3:
        setup_twin_tab()
    with tab4:
        setup_sensor_tab()
    
    # new message processing
    while not st.session_state.response_queue.empty():
        task = st.session_state.response_queue.get()
        result = task.get("result", "")
        agent_id = task["agent_id"]
        if agent_id == 1:
            if (contains_json(result)):
                st.session_state.interview_completed = True
        elif agent_id == 2:
            print(result)
            st.session_state.db_schema = result
        elif agent_id == 3:
            pass
        else:
            continue
        st.rerun()

    time.sleep(10)
    st.rerun()


def main():
    global requests_session
    requests_session = requests.Session()
    retry = Retry(connect=3, backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    requests_session.mount('http://', adapter)
    requests_session.mount('https://', adapter)
    initialize_ui()

if __name__ == '__main__':
    main()
