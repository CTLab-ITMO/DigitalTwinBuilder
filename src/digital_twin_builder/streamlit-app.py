# streamlit_app.py
import streamlit as st
import requests
import time
import json
import threading
import queue
from datetime import datetime
from prompts import system as sys_prompts

# Configuration
API_URL = "http://localhost:8000"  # Change to your API URL
if 'response_queue' not in st.session_state:
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
        response = requests.post(
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
    while (poll < max_poll):
        task = get_task_status(task_id)
        print(str(task))
        if task and task["status"] == "completed":
            response_queue.put(task)
            break
        else: 
            time.sleep(1)
        poll += 1


def create_new_conversation():
    """Create a new conversation"""
    response = requests.post(
        f"{API_URL}/conversations",
        params={"user_id": "streamlit_user", "title": "New Chat"}
    )
    if response.status_code == 200:
        st.session_state.conversation_id = response.json()["conversation_id"]
        st.session_state.messages = []
    response = add_message_to_conversation(st.session_state.conversation_id, "system", sys_prompts.UI)
    if response is not None:
        submit_chat_to_agent(1, st.session_state.conversation_id, {})
        st.rerun()

def load_conversation(conversation_id):
    """Load a conversation from API"""
    response = requests.get(f"{API_URL}/conversations/{conversation_id}")
    if response.status_code == 200:
        data = response.json()
        st.session_state.conversation_id = conversation_id
        st.session_state.messages = data["messages"]

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

def setup_interview_tab():
    agent_id = 1
    st.header("Создание цифрового двойника производства")
    
    if st.session_state.conversation_id is None:
        st.markdown("Пожалуйста, выберите существующий чат или создайте новый")
        return

    load_conversation(st.session_state.conversation_id)
    for message in st.session_state.messages:
        if message["role"] == "system":
            continue
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    while not st.session_state.response_queue.empty():
        task = st.session_state.response_queue.get()
        result = task.get("result", "")
        agent_id = task["agent_id"]
        if agent_id == 1:
            # TODO: add dialog functionality to agent
            bot_response, interview_state_update = _process_agent_response(
                result,
                st.session_state.interview_state
            )

            # st.session_state.interview_state.update(interview_state_update)
            
            st.session_state.chat_history.append({"role": "bot", "content": bot_response})
        elif agent_id == 2:
            st.session_state.db_schema = result
        elif agent_id == 3:
            pass

    with st.expander("Parameters"):
        temperature = st.slider("Temperature", 0.0, 2.0, 0.7, 0.1)
        max_tokens = st.number_input("Max Tokens", 100, 4000, 1000)

    if not st.session_state.get('interview_completed', False):
        user_input = st.chat_input("Введите информацию о вашем производстве...")
        if user_input:
            params = {
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            submit_chat_to_agent(agent_id, st.session_state.conversation_id, params)
        time.sleep(2)
        st.rerun()
    else:
        st.success("Интервью завершено! Перейдите к следующей вкладке.")
        with st.expander("Собранные данные"):
            st.json(st.session_state.interview_result)


def _process_agent_response(response, current_state):
    """Обрабатывает ответ агента и обновляет состояние интервью"""

    return response, None
    # TODO: add dialog functionality to agent
    topic_completed = "следующ" in response.lower() or "перейд" in response.lower()
    
    update = {}
    if topic_completed:
        update['completed_topics'] = current_state['completed_topics'] + [current_state['current_topic']]
        update['current_topic'] = None
    else:
        update['current_topic'] = current_state['current_topic']
    
    return response, update

def setup_database_tab():
    st.header("Настройка базы данных")
    
    if 'interview_result' not in st.session_state:
        st.warning("Пожалуйста, завершите интервью на вкладке 'Интервью с пользователем'")
        return
    
    if 'db_schema' not in st.session_state or st.session.db_schema == "":
        st.session_state.db_schema = ""
        prompt = st.session_state.interview_result
        submit_chat_to_agent(2, prompt, {})
    else:
        st.subheader("Сгенерированная схема базы данных")
        st.json(st.session_state.db_schema)
    
        if st.button("Сохранить схему"):
            st.session_state.db_configured = True
            st.success("Схема базы данных сохранена!")

# def setup_twin_tab():
#     st.header("Конфигурация цифрового двойника")
#     
#     if 'db_schema' not in st.session_state:
#         st.warning("Пожалуйста, настройте базу данных на предыдущей вкладке")
#         return
#     
#     if 'twin_config' not in st.session_state:
# 
#         twin_config = .dt_agent.configure_twin(
#             st.session_state.interview_result,
#             st.session_state.db_schema
#         )
#         st.session_state.twin_config = twin_config
#     
#     st.subheader("Конфигурация цифрового двойника")
#     st.json(st.session_state.twin_config)
#     
#     mode = st.radio("Режим работы", ["Симуляция", "Реальные датчики"])
#     
#     if st.button("Запустить цифровой двойник"):
#         try:
#             .sensor_manager = SensorManager(mode='sim' if mode == "Симуляция" else 'real')
#             .sensor_manager.start()
#             
#             .db_manager = DatabaseManager(
#                 dbname="digital_twin",
#                 user="postgres",
#                 password="omgssmyalg"
#             )
#             .db_manager.create_sensor_tables()
#             
#             st.session_state.sensor_running = True
#             st.success("Цифровой двойник успешно запущен!")
#         except Exception as e:
#             st.error(f"Ошибка запуска: {str(e)}")
#     
#     if st.button("Остановить", disabled=not st.session_state.get('sensor_running', False)):
#         .sensor_manager.stop()
#         if .db_manager:
#             .db_manager.close()
#         st.session_state.sensor_running = False
#         st.success("Работа цифрового двойника остановлена")
# 
# def setup_sensor_tab():
#     st.header("Мониторинг производства")
#     
#     if not st.session_state.get('sensor_running', False):
#         st.warning("Цифровой двойник не запущен")
#         return
#     
#     data = .sensor_manager.get_data()
#     if data:
#         .display_sensor_data(data)

def init_session_state():
    """Initialize session state for chat"""
    if 'conversation_id' not in st.session_state:
        st.session_state.conversation_id = None
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'conversations' not in st.session_state:
        st.session_state.conversations = []
    if 'tasks' not in st.session_state:
        st.session_state.tasks = []

def initialize_ui():
    st.set_page_config(page_title="Digital Twin Builder", layout="wide")
    st.title("Digital Twin Builder🏭")

    init_session_state()
    
    with st.sidebar:
        st.title("💬 Conversations")
        
        # Load conversations
        response = requests.get(f"{API_URL}/conversations", params={"user_id": "streamlit_user", "limit": 20})
        if response.status_code == 200:
            st.session_state.conversations = response.json()["conversations"]
        
        # New chat button
        if st.button("➕ New Chat", use_container_width=True):
            create_new_conversation()
        
        st.divider()
        
        # list conversations
        for conv in st.session_state.conversations:
            title = conv.get("title", f"chat {conv['id'][:8]}")
            if st.button(title, key=conv["id"], use_container_width=True):
                load_conversation(conv["id"])

        st.header("agent status")
        
        for agent_id in [1, 2, 3]:
            status = get_agent_status(agent_id)
            status_color = {
                "idle": "🟢",
                "busy": "🟡",
                "offline": "🔴"
            }.get(status.get("status", "offline"), "⚪")
            
            st.markdown(f"**agent {agent_id}** {status_color}")
            caption_str = f"status: {status.get('status', 'offline')}"

            response = requests.get(f"{API_URL}/queue/{agent_id}", timeout=5)
            if response.status_code == 200:
                queue = response.json()
                caption_str += f", pending {queue["pending_count"]}"
                if queue["active_task"]:
                    caption_str += f", active: {queue['active_task']['id'][:8]}..."
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
    # with tab3:
    #     setup_twin_tab()
    # with tab4:
    #     setup_sensor_tab()


def main():
    initialize_ui()

if __name__ == '__main__':
    main()
