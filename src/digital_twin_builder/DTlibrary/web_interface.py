import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import json
from digital_twin_builder.DTlibrary.cores.database import DatabaseManager
from digital_twin_builder.DTlibrary.cores.sensor_manager import SensorManager
from digital_twin_builder.DTlibrary.agents.user_interaction_agent import UserInteractionAgent
from digital_twin_builder.DTlibrary.agents.database_agent import DatabaseAgent
from digital_twin_builder.DTlibrary.agents.digital_twin_agent import DigitalTwinAgent


class DigitalTwinInterface:
    def __init__(self):
        self.ui_agent = UserInteractionAgent()
        self.db_agent = DatabaseAgent()
        self.dt_agent = DigitalTwinAgent()
        self.sensor_manager = None
        self.db_manager = None
        if 'twin_initialized' not in st.session_state:
            st.session_state.twin_initialized = False

        if 'temperature_history' not in st.session_state:
            st.session_state.temperature_history = []

        if 'vibration_history' not in st.session_state:
            st.session_state.vibration_history = []

        self.setup_ui()


    def setup_ui(self):
        st.set_page_config(page_title="Digital Twin Builder", layout="wide")
        st.title("Digital Twin Builder🏭")

        self.tab1, self.tab2, self.tab3, self.tab4 = st.tabs([
            "Интервью с пользователем", 
            "Создание базы данных", 
            "Цифровой двойник",
            "Обзор графиков датчиков"
        ])

        with self.tab1:
            self.setup_interview_tab()
        with self.tab2:
            self.setup_database_tab()
        with self.tab3:
            self.setup_twin_tab()
        with self.tab4:
            self.setup_sensor_tab()

    def setup_interview_tab(self):
        st.header("Создание цифрового двойника производства")

        # Инициализация чата
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []
            st.session_state.interview_finished = False

            # Первый шаг агента (приветствие + тема)
            first_msg = self.ui_agent.run()

            st.session_state.chat_history.append({
                "role": "assistant",
                "content": first_msg
            })

        for msg in st.session_state.chat_history:
            role = "assistant" if msg["role"] == "assistant" else "user"
            with st.chat_message(role):
                st.markdown(msg["content"])

        if st.session_state.interview_finished:
            st.success("Интервью завершено!")
            st.subheader("Итоговый JSON")
            st.json(json.loads(st.session_state.final_json))
            return

        user_input = st.chat_input("Введите ваш ответ...")

        if user_input:
            st.session_state.chat_history.append({
                "role": "user",
                "content": user_input
            })

            agent_response = self.ui_agent.next_step(user_input)

            if self.ui_agent.is_finished() or self.ui_agent.current_topic not in self.ui_agent.topics:
                st.session_state.interview_finished = True
                st.session_state.final_json = agent_response

                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": "✅ Интервью завершено. Вот итоговые данные."
                })

                st.rerun()
            else:
                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": agent_response
                })

                st.rerun()


    def _build_interview_prompt(self, interview_state, user_input):
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

    def _process_agent_response(self, response, current_state):
        topic_completed = "следующ" in response.lower() or "перейд" in response.lower()

        update = {}
        if topic_completed:
            update['completed_topics'] = current_state['completed_topics'] + [current_state['current_topic']]
            update['current_topic'] = None
        else:
            update['current_topic'] = current_state['current_topic']

        return response, update

    def setup_database_tab(self):
        st.header("Настройка базы данных")

        if 'interview_result' not in st.session_state:
            st.warning("Пожалуйста, завершите интервью на вкладке 'Интервью с пользователем'")
            return

        if 'db_schema' not in st.session_state:

            db_schema = self.db_agent.generate_schema(st.session_state.interview_result)
            st.session_state.db_schema = db_schema

        st.subheader("Сгенерированная схема базы данных")
        st.json(st.session_state.db_schema)

        if st.button("Сохранить схему"):
            st.session_state.db_configured = True
            st.success("Схема базы данных сохранена!")

    def setup_twin_tab(self):
        st.header("Конфигурация цифрового двойника")

        if 'db_schema' not in st.session_state:
            st.warning("Пожалуйста, настройте базу данных на предыдущей вкладке")
            return

        if 'twin_config' not in st.session_state:

            twin_config = self.dt_agent.configure_twin(
                st.session_state.interview_result,
                st.session_state.db_schema
            )
            st.session_state.twin_config = twin_config

        st.subheader("Конфигурация цифрового двойника")
        st.json(st.session_state.twin_config)

        mode = st.radio("Режим работы", ["Симуляция", "Реальные датчики"])

        if st.button("Запустить цифровой двойник"):
            try:
                self.sensor_manager = SensorManager(mode='sim' if mode == "Симуляция" else 'real')
                self.sensor_manager.start()

                self.db_manager = DatabaseManager(
                    dbname="digital_twin",
                    user="postgres",
                    password="omgssmyalg"
                )
                self.db_manager.create_sensor_tables()

                st.session_state.sensor_running = True
                st.success("Цифровой двойник успешно запущен!")
            except Exception as e:
                st.error(f"Ошибка запуска: {str(e)}")

        if st.button("Остановить", disabled=not st.session_state.get('sensor_running', False)):
            self.sensor_manager.stop()
            if self.db_manager:
                self.db_manager.close()
            st.session_state.sensor_running = False
            st.success("Работа цифрового двойника остановлена")

    def setup_sensor_tab(self):
        st.header("Панель мониторинга")

        if not st.session_state.get('sensor_running', False):
            st.warning("Цифровой двойник не запущен")
            return

        data = self.sensor_manager.get_data()
        if data:
            self.display_sensor_data(data)

    def setup_sensor_tab(self):
        st.header("Мониторинг производства")

        if not st.session_state.get('sensor_running', False):
            st.warning("Цифровой двойник не запущен")
            return

        data = self.sensor_manager.get_data()
        if data:
            self.display_sensor_data(data)

    def display_sensor_data(self, data):
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

        self.plot_sensor_data(data)

    def plot_sensor_data(self, data):
        col1, col2 = st.columns(2)

        with col1:
            st.session_state.temperature_history.append({
                "timestamp": datetime.fromtimestamp(data["timestamp"]),
                "value": data["sensor_data"].get("temperature", 0)
            })
            temp_df = pd.DataFrame(st.session_state.temperature_history[-100:])
            fig_temp = px.line(temp_df, x="timestamp", y="value", title="Температура")
            st.plotly_chart(fig_temp, use_container_width=True)

        with col2:
            st.session_state.vibration_history.append({
                "timestamp": datetime.fromtimestamp(data["timestamp"]),
                "value": data["sensor_data"].get("vibration", 0)
            })
            vib_df = pd.DataFrame(st.session_state.vibration_history[-100:])
            fig_vib = px.line(vib_df, x="timestamp", y="value", title="Вибрация")
            st.plotly_chart(fig_vib, use_container_width=True)

def main():
    interface = DigitalTwinInterface()

if __name__ == "__main__":
    main()
