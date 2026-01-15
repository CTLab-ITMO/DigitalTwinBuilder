import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import json
import subprocess
import tempfile
import os

from digital_twin_builder.DTlibrary.langgraph_flow import build_digital_twin_graph, TwinState
from digital_twin_builder.DTlibrary.cores.database import DatabaseManager
from digital_twin_builder.DTlibrary.cores.sensor_manager import SensorManager
from digital_twin_builder.DTlibrary.agents.user_interaction_agent import UserInteractionAgent
from digital_twin_builder.DTlibrary.agents.database_agent import DatabaseAgent
from digital_twin_builder.DTlibrary.agents.digital_twin_agent import DigitalTwinAgent

class DigitalTwinInterface:
    def __init__(self):
        self.init_session_state()
        self.setup_ui()

    def init_session_state(self):
        """Инициализирует все необходимые переменные в session_state."""
        
        if 'ui_agent' not in st.session_state:
            st.session_state.ui_agent = UserInteractionAgent()
        
        if 'db_agent' not in st.session_state:
            st.session_state.db_agent = DatabaseAgent()
        if 'dt_agent' not in st.session_state:
            st.session_state.dt_agent = DigitalTwinAgent()

        
        if 'chat_history' not in st.session_state:
            st.session_state.chat_history = []
            
            first_msg = st.session_state.ui_agent.run()
            st.session_state.chat_history.append({"role": "assistant", "content": first_msg})

        
        if 'interview_finished' not in st.session_state:
            st.session_state.interview_finished = False
        if 'interview_result' not in st.session_state:
            st.session_state.interview_result = None

        
        if 'db_schema' not in st.session_state:
            st.session_state.db_schema = None
        if 'simulation_code' not in st.session_state:
            st.session_state.simulation_code = None
        
        if 'langgraph_run' not in st.session_state:
            st.session_state.langgraph_run = False

        
        if 'db_schema_interpretation' not in st.session_state:
            st.session_state.db_schema_interpretation = None
        if 'twin_config' not in st.session_state:
            st.session_state.twin_config = None
        if 'twin_config_interpretation' not in st.session_state:
            st.session_state.twin_config_interpretation = None 

        
        if 'sensor_manager' not in st.session_state:
            st.session_state.sensor_manager = None
        if 'db_manager' not in st.session_state:
            st.session_state.db_manager = None
        if 'sensor_running' not in st.session_state:
            st.session_state.sensor_running = False

        
        
        if 'sensor_history' not in st.session_state:
            st.session_state.sensor_history = {}

        
        if 'db_saved' not in st.session_state:
            st.session_state.db_saved = False
        if 'twin_started' not in st.session_state:
            st.session_state.twin_started = False

        
        if 'critical_thresholds' not in st.session_state:
            st.session_state.critical_thresholds = {}


    def setup_ui(self):
        st.set_page_config(page_title="Digital Twin Builder", layout="wide")
        st.title("Digital Twin Builder 🏭")

        
        self.tab1, self.tab2, self.tab3, self.tab4, self.tab5 = st.tabs([
            "Интервью с пользователем",
            "Создание базы данных",
            "Цифровой двойник",
            "Симуляция PyChrono", 
            "Обзор графиков датчиков"
        ])

        with self.tab1:
            self.setup_interview_tab()
        with self.tab2:
            self.setup_database_tab()
        with self.tab3:
            self.setup_twin_tab()
        with self.tab4: 
            self.setup_simulation_tab()
        with self.tab5:
            self.setup_sensor_tab()

    def setup_interview_tab(self):
        st.header("Создание цифрового двойника производства")

        
        for msg in st.session_state.chat_history:
            role = "assistant" if msg["role"] == "assistant" else "user"
            with st.chat_message(role):
                st.markdown(msg["content"])

        if st.session_state.interview_finished:
            st.success("Интервью завершено!")
            if st.session_state.interview_result:
                st.subheader("Итоговые требования:")
                st.json(st.session_state.interview_result)
            return

        user_input = st.chat_input("Введите ваш ответ...")
        if user_input:
            
            st.session_state.chat_history.append({"role": "user", "content": user_input})

            
            agent_response = st.session_state.ui_agent.next_step(user_input)

            
            if st.session_state.ui_agent.is_finished():
                st.session_state.interview_finished = True
                
                final_result = st.session_state.ui_agent.state.get("requirements", {})
                st.session_state.interview_result = final_result
                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": "✅ Интервью завершено. Переходите к следующим вкладкам."
                })
                
                self.run_langgraph_if_needed()
            else:
                
                if agent_response:
                    st.session_state.chat_history.append({"role": "assistant", "content": agent_response})

            
            st.rerun()

    def run_langgraph_if_needed(self):
        """Запускает LangGraph, если он еще не запускался и интервью завершено."""
        if st.session_state.interview_finished and not st.session_state.langgraph_run and st.session_state.interview_result:
            with st.spinner("Запуск LangGraph для генерации схемы БД и симуляции..."):
                try:
                    
                    initial_state: TwinState = {
                        "raw_user_inputs": st.session_state.ui_agent.state.get("raw_user_inputs", []),
                        "requirements": st.session_state.interview_result,
                        "missing_fields": [],
                        "interview_finished": True, 
                        "last_question": None,
                        "db_schema": None,
                        "twin_config": None, 
                        "simulation_code": None
                    }

                    
                    graph = build_digital_twin_graph() 
                    final_state = graph.invoke(initial_state)

                    
                    st.session_state.db_schema = final_state.get("db_schema")
                    st.session_state.simulation_code = final_state.get("simulation_code")
                    
                    st.session_state.langgraph_run = True

                    st.success("LangGraph завершен. Схема БД и код симуляции сгенерированы.")
                except Exception as e:
                    st.error(f"Ошибка при запуске LangGraph: {e}")
                    st.session_state.langgraph_run = True 
                    return 


    def setup_database_tab(self):
        st.header("Настройка базы данных")

        if not st.session_state.interview_result:
            st.warning("Пожалуйста, завершите интервью на вкладке 'Интервью с пользователем'.")
            return

        
        st.subheader("Описание системы")
        description_box = st.empty()
        if st.session_state.interview_result:
            description_text = self.generate_system_description(st.session_state.interview_result)
            description_box.info(description_text)

        
        self.run_langgraph_if_needed()

        
        if st.session_state.db_schema:
            
            if st.session_state.db_schema_interpretation is None:
                try:
                    interpretation = st.session_state.db_agent.interpret_schema(st.session_state.db_schema)
                    st.session_state.db_schema_interpretation = interpretation
                except Exception as e:
                    st.error(f"Ошибка при интерпретации схемы: {e}")

            st.subheader("Сгенерированная схема базы данных")
            st.json(st.session_state.db_schema)

            st.subheader("Визуальное представление схемы")
            
            if st.session_state.db_schema_interpretation is not None:
                st.text_area("Структура базы данных для производства", value=st.session_state.db_schema_interpretation, height=400, disabled=True)
            else:
                st.info("Интерпретация схемы БД не найдена или не сгенерирована.")

            
            if st.button("Сохранить схему и продолжить"):
                st.session_state.db_saved = True
                st.success("Схема сохранена! Можете перейти к следующему шагу.")
        else:
            st.error("Схема базы данных не была сгенерирована.")


    def generate_system_description(self, requirements: dict) -> str:
        """Генерирует текстовое описание системы на основе требований."""
        
        desc = "Объект: "
        if "object" in requirements and "type" in requirements["object"]:
            desc += f"{requirements['object']['type']} "
        if "object" in requirements and "equipment" in requirements["object"]:
            equipment_list = ", ".join(requirements["object"]["equipment"])
            desc += f"на объекте с оборудованием: {equipment_list}."
        else:
            desc += "не указан."

        desc += "\n\nЦели цифрового двойника:\n"
        if "goals" in requirements:
            for i, goal in enumerate(requirements["goals"], 1):
                desc += f"{i}. {goal}\n"

        desc += "\n\nДоступные данные:\n"
        if "data_sources" in requirements and "sensors" in requirements["data_sources"]:
            sensors_list = ", ".join(requirements["data_sources"]["sensors"])
            desc += f"- {sensors_list}"

        desc += "\n\nДанные обновляются каждые "
        if "update_requirements" in requirements and "frequency" in requirements["update_requirements"]:
            desc += f"{requirements['update_requirements']['frequency']}"
        else:
            desc += "не указано"
        desc += " и хранятся "

        if "storage" in requirements and "history_days" in requirements["storage"]:
            desc += f"в течение {requirements['storage']['history_days']} дней."
        else:
            desc += "не указано."

        desc += "\n\nОсобые требования:\n"
        if "integrations" in requirements:
            integrations_list = ", ".join(requirements["integrations"])
            desc += f"- Интеграция с системами: {integrations_list}\n"
        if "security" in requirements:
            criticality = requirements["security"].get("criticality", "не указана")
            desc += f"- Уровень критичности: {criticality}\n"

        return desc

    def setup_twin_tab(self):
        st.header("Конфигурация цифрового двойника")

        
        if not st.session_state.langgraph_run:
             st.warning("Пожалуйста, сначала завершите интервью и перейдите на вкладку 'Создание базы данных' для запуска генерации.")
             return

        if not st.session_state.db_schema:
            st.warning("Пожалуйста, настройте базу данных на предыдущей вкладке.")
            return

        
        if not st.session_state.twin_config:
            with st.spinner("Конфигурация цифрового двойника..."):
                try:
                    
                    
                    
                    config = st.session_state.dt_agent.configure_twin_old(st.session_state.interview_result, st.session_state.db_schema)
                    st.session_state.twin_config = config

                    
                    
                    
                    
                    
                    

                    st.success("Конфигурация цифрового двойника готова!")
                except Exception as e:
                    st.error(f"Ошибка при конфигурации двойника: {e}")
                    return 

        st.subheader("Схема базы данных")
        st.json(st.session_state.db_schema)

        st.subheader("Конфигурация цифрового двойника")
        st.json(st.session_state.twin_config)

        st.subheader("Детальное описание компонентов цифрового двойника")
        
        
        
        
        
        st.info("Конфигурация была сгенерирована на основе требований и схемы БД.")


        
        st.subheader("Режим работы сенсоров")
        mode = st.radio("", ["Симуляция", "Реальное оборудование"], index=0, key="sensor_mode_radio")

        
        if st.button("Запустить цифровой двойник"):
            try:
                
                st.session_state.sensor_manager = SensorManager(mode='sim' if mode == "Симуляция" else 'real')
                st.session_state.sensor_manager.start()

                
                st.session_state.db_manager = DatabaseManager(
                    dbname="digital_twin",
                    user="postgres",
                    password="omgssmyalg"
                )
                

                st.session_state.sensor_running = True
                st.session_state.twin_started = True
                
                self.clear_sensor_history()
                st.success("Цифровой двойник успешно запущен!")
            except Exception as e:
                st.error(f"Ошибка запуска: {str(e)}")

        
        if st.button("Остановить цифровой двойник", disabled=not st.session_state.get('sensor_running', False)):
            if st.session_state.sensor_manager:
                st.session_state.sensor_manager.stop()
            if st.session_state.db_manager:
                st.session_state.db_manager.close()
            st.session_state.sensor_running = False
            st.session_state.twin_started = False
            
            self.clear_sensor_history()
            st.success("Работа цифрового двойника остановлена.")

    def clear_sensor_history(self):
        """Очищает историю всех датчиков."""
        st.session_state.sensor_history = {} 


    def setup_simulation_tab(self):
        st.header("Генерация и Запуск PyChrono Симуляции")

        
        if not st.session_state.langgraph_run:
             st.warning("Пожалуйста, сначала завершите интервью и перейдите на вкладку 'Создание базы данных' для запуска генерации.")
             return

        if not st.session_state.db_schema:
            st.warning("Пожалуйста, настройте базу данных на предыдущей вкладке.")
            return

        
        
        if not st.session_state.simulation_code:
             
             st.error("Код симуляции не был сгенерирован LangGraph.")
             return

        st.subheader("Сгенерированный код симуляции PyChrono")
        
        st.code(st.session_state.simulation_code, language='python')

        
        st.download_button(
            label="Скачать файл симуляции (.py)",
            data=st.session_state.simulation_code,
            file_name="digital_twin_simulation.py",
            mime="application/x-python-code"
        )

        
        if st.button("Запустить симуляцию (в отдельном процессе)"):
            if st.session_state.simulation_code:
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(st.session_state.simulation_code)
                    temp_script_path = f.name

                try:
                    st.warning("Запуск симуляции напрямую из интерфейса отключен для безопасности. Сохраните файл и запустите его вручную в среде с установленным PyChrono.")
                    
                    
                    
                    
                    
                    
                    
                except subprocess.TimeoutExpired:
                    st.error("Симуляция превысила время ожидания.")
                except subprocess.CalledProcessError as e:
                    st.error(f"Ошибка при выполнении симуляции: {e}")
                except Exception as e:
                    st.error(f"Неизвестная ошибка при запуске симуляции: {e}")
                finally:
                    
                    os.unlink(temp_script_path)
            else:
                st.warning("Нет кода для запуска.")


    def setup_sensor_tab(self):
        st.header("Панель мониторинга")

        if not st.session_state.get('sensor_running', False):
            st.warning("Цифровой двойник не запущен. Перейдите на вкладку 'Цифровой двойник' и запустите его.")
            return

        
        st.subheader("Режим сенсоров")
        sensor_mode = st.radio("", ["Симуляция", "Реальное оборудование"], index=0, key="sensor_mode_monitoring")

        
        data = st.session_state.sensor_manager.get_data()
        if data:
            self.update_sensor_history(data)
            self.display_current_sensor_data(data)
            self.check_critical_alerts(data)
        else:
            st.info("Ожидание данных от сенсоров...")

        
        st.subheader("Анализ данных")
        
        analysis_period = st.selectbox("Анализ данных за:", ["15 минут", "1 час", "6 часов", "1 день"], index=0)

        
        self.plot_all_sensor_data()

    def update_sensor_history(self,  dict):
        """Обновляет историю для каждого параметра на основе полученных данных."""
        timestamp = datetime.fromtimestamp(data["timestamp"])
        for param, value in data["sensor_data"].items():
            if isinstance(value, (int, float)): 
                
                if param not in st.session_state.sensor_history:
                    st.session_state.sensor_history[param] = []
                
                st.session_state.sensor_history[param].append({"timestamp": timestamp, "value": value})
                
                history_limit = 100
                st.session_state.sensor_history[param] = st.session_state.sensor_history[param][-history_limit:]

    def display_current_sensor_data(self,  dict):
        """Отображает текущие значения датчиков."""
        st.subheader("Текущие показания сенсоров")
        sensor_data = data["sensor_data"]
        display_data = []

        
        
        
        default_param_mapping = {
            "temperature": ("Температура", "°C"),
            "casting_speed": ("Скорость", "м/мин"),
            "cooling_water_flow": ("Расход воды", "л/мин"),
            "vibration_level": ("Вибрация", "м/с²"),
            "wear_level": ("Износ", "%"),
            "defect_count": ("Дефекты", "шт"),
            "quality_score": ("Качество", "/100"),
            "pressure": ("Давление", "Па"),
            "level": ("Уровень", "м"),
        }

        for param, value in sensor_data.items():
            if isinstance(value, (int, float)):
                
                display_name = param
                unit = ""
                if st.session_state.twin_config and "visualization" in st.session_state.twin_config:
                     
                     
                     vis_sensors = st.session_state.twin_config.get("visualization", {}).get("sensors", {})
                     param_vis = vis_sensors.get(param, {})
                     display_name = param_vis.get("display_name", default_param_mapping.get(param, (param, ""))[0])
                     unit = param_vis.get("unit", default_param_mapping.get(param, ("", ""))[1])
                else:
                    
                    display_name, unit = default_param_mapping.get(param, (param, ""))

                display_data.append({
                    "Параметр": display_name,
                    "Значение": value,
                    "Единица": unit
                })

        if display_data: 
            df_display = pd.DataFrame(display_data)
            st.dataframe(df_display, use_container_width=True)
        else:
            st.info("Нет числовых данных для отображения.")

    def check_critical_alerts(self,  dict):
        """Проверяет критические предупреждения и отображает их."""
        alerts = []
        sensor_data = data["sensor_data"]
        timestamp = datetime.fromtimestamp(data["timestamp"])

        
        
        thresholds = st.session_state.critical_thresholds 

        
        for param, value in sensor_data.items():
            if isinstance(value, (int, float)):
                
                if st.session_state.twin_config:
                    alerts_config = st.session_state.twin_config.get("alerts", {}).get("rules", [])
                    for rule in alerts_config:
                         if rule.get("parameter") == param:
                             condition = rule.get("condition", ">")
                             threshold_val = rule.get("threshold", float('inf'))
                             if (condition == ">" and value > threshold_val) or \
                                (condition == "<" and value < threshold_val) or \
                                (condition == "=" and value == threshold_val):
                                 alerts.append(f"⚠️ [{timestamp.strftime('%H:%M:%S')}] {rule.get('message', f'{param} Alert: {value}')}")
                
                
                
                
                
                

        if alerts:
            st.error("КРИТИЧЕСКИЕ ПРЕДУПРЕЖДЕНИЯ:")
            for alert in alerts:
                st.write(alert)

    def plot_all_sensor_data(self):
        """Создает и отображает графики для всех доступных датчиков."""
        
        available_params = list(st.session_state.sensor_history.keys())

        if not available_params:
            st.info("Нет данных для построения графиков.")
            return

        
        num_cols = 2
        cols = st.columns(num_cols)

        for i, param in enumerate(available_params):
            history_list = st.session_state.sensor_history[param]
            col_idx = i % num_cols
            with cols[col_idx]:
                if history_list: 
                    df_plot = pd.DataFrame(history_list)
                    if not df_plot.empty: 
                        
                        display_name = param
                        unit = ""
                        if st.session_state.twin_config and "visualization" in st.session_state.twin_config:
                            vis_sensors = st.session_state.twin_config.get("visualization", {}).get("sensors", {})
                            param_vis = vis_sensors.get(param, {})
                            display_name = param_vis.get("display_name", param)
                            unit = param_vis.get("unit", "")
                        else:
                            
                            default_mapping = {
                                "temperature": ("Температура", "°C"),
                                "casting_speed": ("Скорость", "м/мин"),
                                "cooling_water_flow": ("Расход воды", "л/мин"),
                                "vibration_level": ("Вибрация", "м/с²"),
                                "wear_level": ("Износ", "%"),
                                "defect_count": ("Дефекты", "шт"),
                                "quality_score": ("Качество", "/100"),
                                "pressure": ("Давление", "Па"),
                                "level": ("Уровень", "м"),
                            }
                            display_name, unit = default_mapping.get(param, (param, ""))
                        
                        full_title = f"{display_name}, {unit}" if unit else display_name
                        fig = px.line(df_plot, x="timestamp", y="value", title=full_title)
                        
                        
                        if st.session_state.twin_config:
                            alerts_config = st.session_state.twin_config.get("alerts", {}).get("rules", [])
                            for rule in alerts_config:
                                if rule.get("parameter") == param:
                                    threshold_val = rule.get("threshold", None)
                                    condition = rule.get("condition", "")
                                    if threshold_val is not None:
                                        color = "red" if "critical" in rule.get("severity", "").lower() else "orange"
                                        dash_style = "dash"
                                        fig.add_hline(
                                            y=threshold_val,
                                            line_dash=dash_style,
                                            line_color=color,
                                            annotation_text=f"{condition} {threshold_val}"
                                        )

                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.caption(f"DataFrame пуст для {param}.")
                else:
                    st.caption(f"Нет данных для {param}.")


def main():
    DigitalTwinInterface()

if __name__ == "__main__":
    main()