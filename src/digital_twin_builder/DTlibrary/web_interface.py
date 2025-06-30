import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import json
from cores.database import DatabaseManager
from cores.sensor_manager import SensorManager
from agents.user_interaction_agent import UserInteractionAgent
from agents.database_agent import DatabaseAgent
from agents.digital_twin_agent import DigitalTwinAgent


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
        
        if 'chat_history' not in st.session_state:
            st.session_state.chat_history = []
            st.session_state.interview_state = {
                'current_topic': None,
                'completed_topics': [],
                'collected_data': {},
                'awaiting_response': False
            }
            
            initial_response = self._get_initial_interview_questions()
            st.session_state.chat_history.append({
                "role": "bot", 
                "content": initial_response
            })
        
        for message in st.session_state.chat_history:
            role = "assistant" if message["role"] == "bot" else "user"
            with st.chat_message(role):
                st.markdown(message["content"])
        
        if not st.session_state.get('interview_completed', False):
            user_input = st.chat_input("Введите информацию о вашем производстве...")
            
            if user_input:
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                
                bot_response = self._get_next_interview_question(user_input)
                
                if st.session_state.interview_state.get('interview_completed'):
                    bot_response += "\n\nСпасибо! Интервью завершено. Перейдите к следующей вкладке для настройки базы данных."
                    st.session_state.interview_completed = True
                    st.session_state.interview_result = st.session_state.interview_state['collected_data']
                
                st.session_state.chat_history.append({"role": "bot", "content": bot_response})
                st.rerun()
        else:
            st.success("Интервью завершено! Перейдите к следующей вкладке.")
            with st.expander("Собранные данные"):
                st.json(st.session_state.interview_result)

    def _get_initial_interview_questions(self):
        return """Здравствуйте! Для построения цифрового двойника производства, пожалуйста, предоставьте следующую информацию:Add commentMore actions
            
            1. Основные характеристики объекта
            2. Цели и задачи цифрового двойника
            3. Доступные данные и источники информации
            4. Временные рамки и частота обновления данных
            5. Особые требования или ограниченияAdd commentMore actions
            
            Пожалуйста, начните с описания вашего производства."""

    def _get_next_interview_question(self, user_input):
        """Генерирует следующий вопрос на основе ответа пользователя"""

        current_state = st.session_state.interview_state
        topics = [
            "general_info",
            "production_processes",
            "data_monitoring",
            "twin_requirements"
        ]
        
        if not current_state['current_topic']:
            current_topic = topics[0]
            current_state['current_topic'] = current_topic
            current_state['collected_data'][current_topic] = []
        
        current_state['collected_data'][current_state['current_topic']].append(user_input)
        
        questions = {
            "general_info": [
                "Расскажите подробнее об организационной структуре предприятия",
                "Каковы площади производства и как они распределены?",
                "Сколько сотрудников работает на предприятии?"
            ],
            "production_processes": [
                "Опишите основные технологические этапы производства",
                "Какое оборудование является наиболее критичным?",
                "Какие параметры процессов требуют постоянного контроля?"
            ],
            "data_monitoring": [
                "Какие датчики и системы мониторинга уже установлены?",
                "Как часто собираются данные с оборудования?",
                "Где и как хранятся собранные данные?"
            ],
            "twin_requirements": [
                "Какие процессы должны быть смоделированы в цифровом двойнике?",
                "Какие показатели вы хотите визуализировать в первую очередь?",
                "Нужна ли интеграция с другими системами предприятия?"
            ]
        }
        
        topic_questions = questions[current_state['current_topic']]
        
        asked_count = len(current_state['collected_data'][current_state['current_topic']])
        
        if asked_count < len(topic_questions):
            return topic_questions[asked_count]
        else:
            current_idx = topics.index(current_state['current_topic'])
            if current_idx + 1 < len(topics):
                current_state['current_topic'] = topics[current_idx + 1]
                current_state['collected_data'][current_state['current_topic']] = []
                return questions[current_state['current_topic']][0]
            else:
                current_state['interview_completed'] = True
                return "Благодарим вас за предоставленную информацию!"
            

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