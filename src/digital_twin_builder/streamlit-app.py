# streamlit_app.py
import streamlit as st
import requests
import time
import json
import threading
import queue
from datetime import datetime

# Configuration
API_URL = "http://localhost:8000"  # Change to your API URL
if 'response_queue' not in st.session_state:
    st.session_state.response_queue = queue.Queue()
# Helper functions
def submit_task(agent_id, prompt, params):
    """Submit task to API"""
    try:
        response = requests.post(
            f"{API_URL}/tasks",
            json={
                "agent_id": agent_id,
                "prompt": prompt,
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
            response_queue.put(task.get('result', 'No result'))
            break
        else: 
            time.sleep(1)
        poll += 1

def submit_prompt_to_agent(agent_id, prompt, params):
    task_info = submit_task(agent_id, prompt, params)
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


def initialize_ui():
    st.set_page_config(page_title="Digital Twin Builder", layout="wide")
    st.title("Digital Twin Builder🏭")

    # Initialize session state
    if 'tasks' not in st.session_state:
        st.session_state.tasks = []

    with st.sidebar:
        st.header("Agent Status")
        
        for agent_id in [1, 2, 3]:
            status = get_agent_status(agent_id)
            status_color = {
                "idle": "🟢",
                "busy": "🟡",
                "offline": "🔴"
            }.get(status.get("status", "offline"), "⚪")
            
            st.markdown(f"**Agent {agent_id}** {status_color}")
            st.caption(f"Status: {status.get('status', 'offline')}")
        
            try:
                response = requests.get(f"{API_URL}/queue/{agent_id}", timeout=5)
                if response.status_code == 200:
                    queue = response.json()
                    with st.expander(f"Tasks"):
                        st.metric("Pending", queue["pending_count"])
                        if queue["active_task"]:
                            st.caption(f"Active: {queue['active_task']['id'][:8]}...")
            except:
                st.caption(f"Agent {agent_id}: Unavailable")

    tab1, tab2, tab3, tab4 = st.tabs([
        "Интервью с пользователем", 
        "Создание базы данных", 
        "Цифровой двойник",
        "Обзор графиков датчиков"
    ])
        
    with tab1:
        setup_interview_tab()
    # with tab2:
    #     setup_database_tab()
    # with tab3:
    #     setup_twin_tab()
    # with tab4:
    #     setup_sensor_tab()

def setup_interview_tab():
    agent_id = 1
    st.header("Создание цифрового двойника производства")
    
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
        st.session_state.interview_state = {
            'current_topic': None,
            'completed_topics': [],
            'collected_data': {},
            'awaiting_response': False
        }
        
        initial_prompt = """Ты - агент для сбора информации о производстве с целью создания цифрового двойника. Проведи интервью на русском языке, задавая четкие вопросы по следующим те

1. Общая информация о предприятии:
   - Основная деятельность и продукция
   - Организационная структура
   - Площади производства

2. Производственные процессы:
   - Основные технологические этапы
   - Критическое оборудование
   - Проблемные участки

3. Данные и мониторинг:
   - Используемые датчики и их параметры
   - Системы сбора данных
   - Текущие показатели эффективности

4. Требования к цифровому двойнику:
   - Какие процессы нужно моделировать
   - Какие показатели отслеживать
   - Интеграция с существующими системами

Веди диалог естественно, уточняй непонятные моменты. В конце представь собранную информацию в виде JSON структуры на русском языке. 
Начни диалог с приветствия и краткого перечисления пунктов, которые нужно обсудить."""
        submit_prompt_to_agent(agent_id, initial_prompt, {})
    for message in st.session_state.chat_history:
        role = "assistant" if message["role"] == "bot" else "user"
        with st.chat_message(role):
            st.markdown(message["content"])


    while not st.session_state.response_queue.empty():
        result = st.session_state.response_queue.get()

        bot_response, interview_state_update = _process_agent_response(
            result,
            st.session_state.interview_state
        )

        st.session_state.interview_state.update(interview_state_update)
           
        if len(st.session_state.interview_state['completed_topics']) == 4:
            st.session_state.interview_completed = True
            st.session_state.interview_result = {
                "general_info": "\n".join(st.session_state.interview_state['collected_data'].get("general_info", [])),
                "production_processes": "\n".join(st.session_state.interview_state['collected_data'].get("production_processes", [])),
                "data_monitoring": "\n".join(st.session_state.interview_state['collected_data'].get("data_monitoring", [])),
                "twin_requirements": "\n".join(st.session_state.interview_state['collected_data'].get("twin_requirements", []))
            }
            bot_response += "\n\nСпасибо! Интервью завершено. Перейдите к следующей вкладке для настройки базы данных."
        
        st.session_state.chat_history.append({"role": "bot", "content": bot_response})

            
        st.rerun()

    with st.expander("Parameters"):
        temperature = st.slider("Temperature", 0.0, 2.0, 0.7, 0.1)
        max_tokens = st.number_input("Max Tokens", 100, 4000, 1000)

    if not st.session_state.get('interview_completed', False):
        user_input = st.chat_input("Введите информацию о вашем производстве...")
        
        if user_input:
            # Appends chat history
            # Builds prompt
            # POST task
            # Wait for completion
            # Print response

            if prompt := _build_interview_prompt(
                    st.session_state.interview_state,
                    user_input
                ):
                st.session_state.chat_history.append({
                    "role": "user", 
                    "content": user_input
                })
                params = {
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
                submit_prompt_to_agent(agent_id, prompt, params)
        time.sleep(2)
        st.rerun()
           # st.session_state.chat_history.append({"role": "user", "content": user_input})
           # 
           # current_topic = st.session_state.interview_state['current_topic']
           # if current_topic:
           #     st.session_state.interview_state['collected_data'].setdefault(current_topic, []).append(user_input)
           # 
           # prompt = ._build_interview_prompt(
           #     st.session_state.interview_state,
           #     user_input
           # )
           # 
           # try:
           #     response = .ui_agent.model(
           #         prompt,
           #         max_length=2048,
           #         num_return_sequences=1
           #     )[0]['generated_text']
           #     
           #     bot_response, interview_state_update = ._process_agent_response(
           #         response,
           #         st.session_state.interview_state
           #     )
           #     
           #     st.session_state.interview_state.update(interview_state_update)
           #     
           #     if len(st.session_state.interview_state['completed_topics']) == 4:
           #         st.session_state.interview_completed = True
           #         st.session_state.interview_result = {
           #             "general_info": "\n".join(st.session_state.interview_state['collected_data'].get("general_info", [])),
           #             "production_processes": "\n".join(st.session_state.interview_state['collected_data'].get("production_processes", [])),
           #             "data_monitoring": "\n".join(st.session_state.interview_state['collected_data'].get("data_monitoring", [])),
           #             "twin_requirements": "\n".join(st.session_state.interview_state['collected_data'].get("twin_requirements", []))
           #         }
           #         bot_response += "\n\nСпасибо! Интервью завершено. Перейдите к следующей вкладке для настройки базы данных."
           #     
           #     st.session_state.chat_history.append({"role": "bot", "content": bot_response})
           #     
           # except Exception as e:
           #     st.error(f"Ошибка при обработке ответа: {str(e)}")
           # 
           # st.rerun()
    else:
        st.success("Интервью завершено! Перейдите к следующей вкладке.")
        with st.expander("Собранные данные"):
            st.json(st.session_state.interview_result)


def _build_interview_prompt(interview_state, user_input):
    """Строит промпт для продолжения интервью"""
    topics = {
        "general_info": "Общая информация о предприятии",
        "production_processes": "Производственные процессы",
        "data_monitoring": "Данные и мониторинг",
        "twin_requirements": "Требования к цифровому двойнику"
    }
    
    current_topic = interview_state['current_topic']
    if not current_topic or current_topic in interview_state['completed_topics']:
        for topic in topics:
            if topic not in interview_state['completed_topics']:
                current_topic = topic
                break
    
    prompt = f"""Ты проводишь интервью для создания цифрового двойника металлургического производства. Текущая тема: {topics[current_topic]}.
    
Уже собрана следующая информация:
{json.dumps(interview_state['collected_data'], ensure_ascii=False, indent=2)}

Последний ответ пользователя: {user_input}

Сформулируй уточняющий вопрос или, если информации достаточно, кратко суммируй собранное и переходи к следующей теме.
Используй естественный, дружелюбный тон на русском языке."""
    
    return prompt

def _process_agent_response(response, current_state):
    """Обрабатывает ответ агента и обновляет состояние интервью"""
    topic_completed = "следующ" in response.lower() or "перейд" in response.lower()
    
    update = {}
    if topic_completed:
        update['completed_topics'] = current_state['completed_topics'] + [current_state['current_topic']]
        update['current_topic'] = None
    else:
        update['current_topic'] = current_state['current_topic']
    
    return response, update

# def setup_database_tab():
#     st.header("Настройка базы данных")
#     
#     if 'interview_result' not in st.session_state:
#         st.warning("Пожалуйста, завершите интервью на вкладке 'Интервью с пользователем'")
#         return
#     
#     if 'db_schema' not in st.session_state:
# 
#         db_schema = .db_agent.generate_schema(st.session_state.interview_result)
#         st.session_state.db_schema = db_schema
#     
#     st.subheader("Сгенерированная схема базы данных")
#     st.json(st.session_state.db_schema)
#     
#     if st.button("Сохранить схему"):
#         st.session_state.db_configured = True
#         st.success("Схема базы данных сохранена!")
# 
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

def main():

    initialize_ui()
    # Main UI
    # st.title("🤖 LLM Agent Control Panel")
    
    # Sidebar - Agent Status
        
    # # Main Area - Task Submission
    # col1, col2 = st.columns([2, 1])
    # 
    # with col1:
    #     st.header("Submit Task")
    #     
    #     with st.form("task_form"):
    #         agent_id = st.selectbox("Agent", [1, 2, 3], key="agent_select")
    #         prompt = st.text_area("Prompt", height=150, 
    #             placeholder="Enter your prompt here...")
    #         
    #         with st.expander("Parameters"):
    #             temperature = st.slider("Temperature", 0.0, 2.0, 0.7, 0.1)
    #             max_tokens = st.number_input("Max Tokens", 100, 4000, 1000)
    #         
    #         submitted = st.form_submit_button("Submit")
    #         
    #         if submitted and prompt:
    #             params = {
    #                 "temperature": temperature,
    #                 "max_tokens": max_tokens
    #             }
    #             
    #             task_info = submit_task(agent_id, prompt, params)
    #             if task_info:
    #                 st.success(f"Task submitted! ID: {task_info['task_id'][:8]}...")
    #                 st.session_state.tasks.append(task_info['task_id'])
    # 
    # with col2:
    #     st.header("Queue Status")
    #     
    #     for agent_id in [1, 2, 3]:
    #         try:
    #             response = requests.get(f"{API_URL}/queue/{agent_id}", timeout=5)
    #             if response.status_code == 200:
    #                 queue = response.json()
    #                 with st.expander(f"Agent {agent_id}"):
    #                     st.metric("Pending", queue["pending_count"])
    #                     if queue["active_task"]:
    #                         st.caption(f"Active: {queue['active_task']['id'][:8]}...")
    #         except:
    #             st.caption(f"Agent {agent_id}: Unavailable")
    # 
    # # Task Monitor
    # st.header("Task Monitor")
    # 
    # if st.session_state.tasks:
    #     # Refresh button
    #     if st.button("🔄 Refresh", type="secondary"):
    #         st.rerun()
    #     
    #     # Display tasks
    #     for task_id in st.session_state.tasks[-5:]:  # Last 5 tasks
    #         task = get_task_status(task_id)
    #         
    #         if task:
    #             with st.container():
    #                 col1, col2, col3 = st.columns([3, 1, 1])
    #                 
    #                 with col1:
    #                     st.text(f"ID: {task_id[:12]}...")
    #                     st.caption(f"Prompt: {task['prompt'][:100]}...")
    #                     st.caption(f"Created: {task['created_at'][:19]}")
    #                 
    #                 with col2:
    #                     status = task['status']
    #                     if status == 'completed':
    #                         st.success("✅ Done")
    #                     elif status == 'processing':
    #                         st.warning("🔄 Processing")
    #                     elif status == 'pending':
    #                         st.info("⏳ Pending")
    #                     else:
    #                         st.error("❌ Failed")
    #                 
    #                 with col3:
    #                     if status == 'completed':
    #                         if st.button("View", key=f"view_{task_id}"):
    #                             st.text_area("Result", task.get('result', 'No result'), 
    #                                        height=200, key=f"result_{task_id}")
    #                     elif status == 'failed':
    #                         st.error(task.get('error', 'Unknown error'))
    #                 
    #                 st.divider()
    # else:
    #     st.info("No tasks submitted yet.")
    # 
    # # Auto-refresh option
    # if st.checkbox("Auto-refresh every 5 seconds"):
    #     time.sleep(5)
    #     st.rerun()

if __name__ == '__main__':
    main()
