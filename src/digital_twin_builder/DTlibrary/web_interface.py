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
from digital_twin_builder.DTlibrary.translations import get_text


class DigitalTwinInterface:
    def __init__(self):
        if 'language' not in st.session_state:
            st.session_state.language = 'ru'
        
        self.ui_agent = UserInteractionAgent(language=st.session_state.language)
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
        if 'casting_speed_history' not in st.session_state:
            st.session_state.casting_speed_history = []
        if 'cooling_water_history' not in st.session_state:
            st.session_state.cooling_water_history = []
        if 'wear_history' not in st.session_state:
            st.session_state.wear_history = []
        if 'quality_history' not in st.session_state:
            st.session_state.quality_history = []
        
        self.setup_ui()

    def t(self, key: str) -> str:
        """Получить перевод по ключу"""
        return get_text(key, st.session_state.language)

    def render_language_selector(self):
        """Отрисовать переключатель языков"""
        col1, col2, col3 = st.columns([6, 2, 1])
        with col2:
            selected_language = st.selectbox(
                self.t("select_language"),
                options=["ru", "en"],
                format_func=lambda x: "🇷🇺 Русский" if x == "ru" else "🇬🇧 English",
                key="language_selector",
                index=0 if st.session_state.language == "ru" else 1
            )
            
            if selected_language != st.session_state.language:
                st.session_state.language = selected_language
                self.ui_agent.set_language(selected_language)
                st.rerun()

    def setup_ui(self):
        st.set_page_config(page_title=self.t("app_title"), layout="wide")
        st.title(self.t("app_title"))
        
        self.render_language_selector()
        
        tab_titles = [
            self.t("tab_interview"),     
            self.t("tab_database"),     
            self.t("tab_digital_twin"),  
            self.t("tab_sensors")        
        ]
        
        self.tab1, self.tab2, self.tab3, self.tab4 = st.tabs(tab_titles)
        
        with self.tab1:
            self.setup_interview_tab()
        with self.tab2:
            self.setup_database_tab()
        with self.tab3:
            self.setup_twin_tab()
        with self.tab4:
            self.setup_sensor_tab()

    def setup_interview_tab(self):
        st.header(self.t("interview_header"))

        if 'chat_history' not in st.session_state:
            st.session_state.chat_history = []
            initial_message = self.t("interview_welcome_message")
            st.session_state.chat_history.append({"role": "assistant", "content": initial_message})
            st.session_state.interview_completed = False
        else:
            if len(st.session_state.chat_history) > 0 and st.session_state.chat_history[0]["role"] == "assistant":
                current_welcome = self.t("interview_welcome_message")
                if st.session_state.chat_history[0]["content"] != current_welcome:
                    st.session_state.chat_history[0]["content"] = current_welcome        
        
        for message in st.session_state.chat_history:
            if message["role"] == "assistant":
                with st.chat_message("assistant"):
                    st.markdown(message["content"])
            else:
                with st.chat_message("user"):
                    st.markdown(message["content"])
        
        if not st.session_state.get('interview_completed', False):
            user_input = st.chat_input(self.t("interview_input_placeholder"))
            
            if user_input:
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                
                try:
                    response = self.ui_agent.run(
                        user_message=user_input,
                        chat_history=st.session_state.chat_history
                    )
                    
                    st.session_state.chat_history.append({"role": "assistant", "content": response["message"]})
                    
                    if response.get("completed", False):
                        st.session_state.interview_completed = True
                        st.session_state.interview_result = response.get("requirements", {})
                        st.session_state.interview_result["status"] = "completed"
                        
                except Exception as e:
                    error_messages = {
                        "ru": f"Произошла ошибка: {str(e)}. Попробуйте переформулировать ваш запрос.",
                        "en": f"An error occurred: {str(e)}. Please try to rephrase your request."
                    }
                    error_msg = error_messages.get(st.session_state.language, error_messages["ru"])
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
                
                st.rerun()
        else:
            st.success(self.t("interview_completed"))
            
            expander_labels = {
                "ru": "Просмотр собранных требований",
                "en": "View collected requirements"
            }
            with st.expander(expander_labels.get(st.session_state.language, expander_labels["ru"])):
                st.json(st.session_state.interview_result)
            
            restart_labels = {
                "ru": "Начать новое интервью",
                "en": "Start new interview"
            }
            if st.button(restart_labels.get(st.session_state.language, restart_labels["ru"]), key="restart_interview"):
                st.session_state.chat_history = []
                st.session_state.interview_completed = False
                if 'interview_result' in st.session_state:
                    del st.session_state.interview_result
                st.rerun()

    def setup_database_tab(self):
        st.header(self.t("database_header"))
        
        if 'interview_result' not in st.session_state:
            st.warning(self.t("requirements_not_ready"))
            return
        
        subheader_labels = {
            "ru": "Описание системы",
            "en": "System Description"
        }
        st.subheader(subheader_labels.get(st.session_state.language, subheader_labels["ru"]))
        st.info(json.dumps(st.session_state.interview_result, ensure_ascii=False, indent=2))
        
        if 'db_schema' not in st.session_state:
            if st.button(f"🔨 {self.t('generate_db_schema')}", key="generate_schema_btn"):
                with st.spinner(self.t("generating_schema")):
                    try:
                        schema = self.db_agent.run(st.session_state.interview_result)
                        st.session_state.db_schema = schema
                        st.rerun()
                    except Exception as e:
                        st.error(f"{self.t('schema_generation_error')}: {str(e)}")
            return
        
        schema_header_labels = {
            "ru": "Сгенерированная схема базы данных",
            "en": "Generated Database Schema"
        }
        st.subheader(schema_header_labels.get(st.session_state.language, schema_header_labels["ru"]))
        st.json(st.session_state.db_schema, expanded=True)
        
        interpret_button_labels = {
            "ru": "📖 Получить описание схемы",
            "en": "📖 Get Schema Description"
        }
        if st.button(interpret_button_labels.get(st.session_state.language, interpret_button_labels["ru"]), key="interpret_schema_btn"):
            with st.spinner(self.t("generating_schema")):
                try:
                    interpretation = self.db_agent.interpret_schema(st.session_state.db_schema)
                    description_header_labels = {
                        "ru": "### Описание схемы БД",
                        "en": "### DB Schema Description"
                    }
                    st.markdown(description_header_labels.get(st.session_state.language, description_header_labels["ru"]))
                    st.write(interpretation)
                except Exception as e:
                    interpretation_error_labels = {
                        "ru": f"Ошибка интерпретации: {str(e)}",
                        "en": f"Interpretation error: {str(e)}"
                    }
                    st.error(interpretation_error_labels.get(st.session_state.language, interpretation_error_labels["ru"]))
        
        success_labels = {
            "ru": "✅ Схема базы данных успешно сгенерирована!",
            "en": "✅ Database schema successfully generated!"
        }
        st.success(success_labels.get(st.session_state.language, success_labels["ru"]))
        
        data_management_labels = {
            "ru": "Управление данными",
            "en": "Data Management"
        }
        st.subheader(data_management_labels.get(st.session_state.language, data_management_labels["ru"]))
        
        col1, col2 = st.columns(2)
        
        with col1:
            test_data_button_labels = {
                "ru": "📊 Сгенерировать тестовые данные (7 дней)",
                "en": "📊 Generate Test Data (7 days)"
            }
            if st.button(test_data_button_labels.get(st.session_state.language, test_data_button_labels["ru"]), key="generate_test_data_btn"):
                try:
                    db_manager = DatabaseManager(
                        dbname="digital_twin",
                        user="postgres",
                        password="omgssmyalg",
                        host="localhost",
                        port="5432"
                    )
                    db_manager.create_sensor_tables()
                    success = db_manager.generate_test_data()
                    db_manager.close()
                    
                    if success:
                        success_test_data_labels = {
                            "ru": "✅ Тестовые данные успешно сгенерированы!",
                            "en": "✅ Test data successfully generated!"
                        }
                        st.success(success_test_data_labels.get(st.session_state.language, success_test_data_labels["ru"]))
                    else:
                        error_test_data_labels = {
                            "ru": "❌ Ошибка генерации тестовых данных",
                            "en": "❌ Error generating test data"
                        }
                        st.error(error_test_data_labels.get(st.session_state.language, error_test_data_labels["ru"]))
                except Exception as e:
                    st.error(f"❌ {self.t('error')}: {str(e)}")
        
        with col2:
            clear_button_labels = {
                "ru": "🗑️ Очистить БД",
                "en": "🗑️ Clear Database"
            }
            if st.button(clear_button_labels.get(st.session_state.language, clear_button_labels["ru"]), key="clear_db_btn"):
                try:
                    db_manager = DatabaseManager(
                        dbname="digital_twin",
                        user="postgres",
                        password="omgssmyalg",
                        host="localhost",
                        port="5432"
                    )
                    success = db_manager.clear_all_data()
                    db_manager.close()
                    
                    if success:
                        clear_success_labels = {
                            "ru": "✅ База данных очищена!",
                            "en": "✅ Database cleared!"
                        }
                        st.success(clear_success_labels.get(st.session_state.language, clear_success_labels["ru"]))
                    else:
                        clear_error_labels = {
                            "ru": "❌ Ошибка очистки БД",
                            "en": "❌ Error clearing database"
                        }
                        st.error(clear_error_labels.get(st.session_state.language, clear_error_labels["ru"]))
                except Exception as e:
                    st.error(f"❌ {self.t('error')}: {str(e)}")

    def setup_twin_tab(self):
        st.header(self.t("dt_header"))
        
        if 'db_schema' not in st.session_state:
            st.warning(self.t("schema_not_ready"))
            return
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader(self.t("dt_requirements"))
            st.json(st.session_state.interview_result)
        with col2:
            st.subheader(self.t("dt_schema"))
            st.json(st.session_state.db_schema)
        
        if st.button(self.t("generate_dt_config")):
            with st.spinner(self.t("generating_config")):
                try:
                    config = self.dt_agent.generate_configuration(
                        st.session_state.interview_result,
                        st.session_state.db_schema
                    )
                    st.session_state.dt_config = config
                    st.rerun()
                except Exception as e:
                    st.error(f"{self.t('config_generation_error')}: {str(e)}")
        
        if st.session_state.get('dt_config'):
            st.success(self.t("generated_config"))
            st.json(st.session_state.dt_config)
            st.download_button(
                label=self.t("download_config"),
                data=json.dumps(st.session_state.dt_config, ensure_ascii=False, indent=2),
                file_name="dt_config.json",
                mime="application/json"
            )
            
            if st.button(self.t("generate_simulation")):
                with st.spinner(self.t("generating_simulation")):
                    try:
                        sim_code = self.dt_agent.generate_simulation_code(
                            st.session_state.interview_result,
                            st.session_state.db_schema
                        )
                        st.session_state.simulation_code = sim_code
                        st.rerun()
                    except Exception as e:
                        st.error(f"{self.t('simulation_generation_error')}: {str(e)}")
            
            if st.session_state.get('simulation_code'):
                st.subheader(self.t("generated_simulation"))
                st.code(st.session_state.simulation_code, language="python")
                st.download_button(
                    label=self.t("download_simulation"),
                    data=st.session_state.simulation_code,
                    file_name="simulation.py",
                    mime="text/plain"
                )
            
            st.divider()
            st.subheader(self.t("modify_dt"))
            modification_request = st.text_area(self.t("modification_request"), height=100)
            
            if st.button(self.t("apply_modifications")):
                if modification_request.strip():
                    with st.spinner(self.t("applying_modifications")):
                        try:
                            modified_config = self.dt_agent.modify_config(
                                st.session_state.dt_config,
                                modification_request
                            )
                            st.session_state.dt_config = modified_config
                            st.success(self.t("modifications_applied"))
                            st.rerun()
                        except Exception as e:
                            st.error(f"{self.t('modification_error')}: {str(e)}")

    def setup_sensor_tab(self):
        st.header(self.t("sensors_header"))
        
        try:
            if not st.session_state.twin_initialized:
                connection_header_labels = {
                    "ru": "Подключение к системе мониторинга",
                    "en": "Connection to Monitoring System"
                }
                st.subheader(connection_header_labels.get(st.session_state.language, connection_header_labels["ru"]))
                
                col1, col2 = st.columns(2)
                
                with col1:
                    connect_db_labels = {
                        "ru": "🔌 Подключиться к БД",
                        "en": "🔌 Connect to Database"
                    }
                    if st.button(connect_db_labels.get(st.session_state.language, connect_db_labels["ru"]), key="connect_db"):
                        try:
                            self.db_manager = DatabaseManager(
                                dbname="digital_twin",
                                user="postgres",
                                password="omgssmyalg",
                                host="localhost",
                                port="5432"
                            )
                            self.db_manager.create_sensor_tables()
                            db_connect_success_labels = {
                                "ru": "✅ Успешно подключено к БД!",
                                "en": "✅ Successfully connected to database!"
                            }
                            st.success(db_connect_success_labels.get(st.session_state.language, db_connect_success_labels["ru"]))
                        except Exception as e:
                            st.error(f"❌ {self.t('error')}: {str(e)}")
                
                with col2:
                    init_sensors_labels = {
                        "ru": "📡 Инициализировать датчики",
                        "en": "📡 Initialize Sensors"
                    }
                    if st.button(init_sensors_labels.get(st.session_state.language, init_sensors_labels["ru"]), key="init_sensors"):
                        try:
                            if not self.db_manager:
                                warning_db_labels = {
                                    "ru": "⚠️ Сначала подключитесь к БД!",
                                    "en": "⚠️ Please connect to database first!"
                                }
                                st.warning(warning_db_labels.get(st.session_state.language, warning_db_labels["ru"]))
                            else:
                                self.sensor_manager = SensorManager(mode='simulated')
                                st.session_state.twin_initialized = True
                                sensors_init_success_labels = {
                                    "ru": "✅ Датчики инициализированы!",
                                    "en": "✅ Sensors initialized!"
                                }
                                st.success(sensors_init_success_labels.get(st.session_state.language, sensors_init_success_labels["ru"]))
                                st.rerun()
                        except Exception as e:
                            st.error(f"❌ {self.t('error')}: {str(e)}")
                
                return
            
            if not self.db_manager:
                self.db_manager = DatabaseManager(
                    dbname="digital_twin",
                    user="postgres",
                    password="omgssmyalg",
                    host="localhost",
                    port="5432"
                )
            
            if not self.sensor_manager:
                self.sensor_manager = SensorManager(mode='simulated')
            
            control_buttons_labels = {
                "ru": "Управление мониторингом",
                "en": "Monitoring Control"
            }
            st.subheader(control_buttons_labels.get(st.session_state.language, control_buttons_labels["ru"]))
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                collect_data_labels = {
                    "ru": "📊 Собрать данные сейчас",
                    "en": "📊 Collect Data Now"
                }
                if st.button(collect_data_labels.get(st.session_state.language, collect_data_labels["ru"]), key="collect_now"):
                    sensor_data = self.sensor_manager.read_all_sensors()
                    self.db_manager.insert_sensor_data(sensor_data)
                    data_saved_labels = {
                        "ru": "✅ Данные сохранены в БД",
                        "en": "✅ Data saved to database"
                    }
                    st.success(data_saved_labels.get(st.session_state.language, data_saved_labels["ru"]))
            
            with col2:
                refresh_labels = {
                    "ru": "🔄 Обновить графики",
                    "en": "🔄 Refresh Charts"
                }
                if st.button(refresh_labels.get(st.session_state.language, refresh_labels["ru"]), key="refresh_graphs"):
                    st.rerun()
            
            with col3:
                stop_labels = {
                    "ru": "⏸️ Остановить мониторинг",
                    "en": "⏸️ Stop Monitoring"
                }
                if st.button(stop_labels.get(st.session_state.language, stop_labels["ru"]), key="stop_monitoring"):
                    st.session_state.twin_initialized = False
                    if self.db_manager:
                        self.db_manager.close()
                    st.rerun()
            
            sensor_data = self.sensor_manager.read_all_sensors()
            
            current_values_labels = {
                "ru": "📈 Текущие показатели",
                "en": "📈 Current Values"
            }
            st.subheader(current_values_labels.get(st.session_state.language, current_values_labels["ru"]))
            
            cols = st.columns(4)
            metrics_labels = {
                "ru": [
                    ("Температура", "°C"),
                    ("Вибрация", "м/с²"),
                    ("Скорость", "м/мин"),
                    ("Расход воды", "л/мин")
                ],
                "en": [
                    ("Temperature", "°C"),
                    ("Vibration", "m/s²"),
                    ("Speed", "m/min"),
                    ("Water Flow", "l/min")
                ]
            }
            
            metrics = metrics_labels.get(st.session_state.language, metrics_labels["ru"])
            metric_keys = ["temperature", "vibration_level", "casting_speed", "cooling_water_flow"]
            
            for col, (label, unit), key in zip(cols, metrics, metric_keys):
                with col:
                    val = sensor_data.get(key, 0)
                    st.metric(label, f"{val:.2f} {unit}")
            
            now = datetime.now()
            history_mappings = [
                ("temperature_history", "temperature"),
                ("vibration_history", "vibration_level"),
                ("casting_speed_history", "casting_speed"),
                ("cooling_water_history", "cooling_water_flow"),
                ("wear_history", "wear_level"),
                ("quality_history", "quality_score")
            ]
            
            for hist_key, data_key in history_mappings:
                if data_key in sensor_data:
                    history = st.session_state.get(hist_key, [])
                    history.append({"timestamp": now, "value": sensor_data[data_key]})
                    if len(history) > 100:
                        history = history[-100:]
                    st.session_state[hist_key] = history
            
            realtime_graphs_labels = {
                "ru": "Графики в реальном времени",
                "en": "Real-time Charts"
            }
            st.subheader(realtime_graphs_labels.get(st.session_state.language, realtime_graphs_labels["ru"]))
            
            graph_titles = {
                "ru": [
                    "Температура стали, °C",
                    "Вибрация, м/с²",
                    "Скорость разливки, м/мин",
                    "Расход воды, л/мин",
                    "Износ оборудования, %",
                    "Качество продукции"
                ],
                "en": [
                    "Steel Temperature, °C",
                    "Vibration, m/s²",
                    "Casting Speed, m/min",
                    "Water Flow, l/min",
                    "Equipment Wear, %",
                    "Product Quality"
                ]
            }
            
            titles = graph_titles.get(st.session_state.language, graph_titles["ru"])
            
            graphs = [
                ("temperature_history", titles[0], 1520, [1500, 1600]),
                ("vibration_history", titles[1], 4.2, [0, 10]),
                ("casting_speed_history", titles[2], 1.8, [0, 3]),
                ("cooling_water_history", titles[3], 1200, [1000, 1500]),
                ("wear_history", titles[4], 85, [0, 100]),
                ("quality_history", titles[5], 80, [0, 100])
            ]
            
            threshold_label = {
                "ru": "Порог",
                "en": "Threshold"
            }
            
            value_label = {
                "ru": "Значение",
                "en": "Value"
            }
            
            time_label = {
                "ru": "Время",
                "en": "Time"
            }
            
            for i in range(0, len(graphs), 2):
                col1, col2 = st.columns(2)
                
                for col, (hist_key, title, threshold, y_range) in zip([col1, col2], graphs[i:i+2]):
                    with col:
                        history = st.session_state.get(hist_key, [])
                        if history:
                            df = pd.DataFrame(history)
                        else:
                            df = pd.DataFrame(columns=["timestamp", "value"])
                        
                        fig = px.line(
                            df,
                            x="timestamp",
                            y="value",
                            title=title,
                            labels={
                                "value": value_label.get(st.session_state.language, value_label["ru"]),
                                "timestamp": time_label.get(st.session_state.language, time_label["ru"])
                            },
                            height=300
                        )
                        fig.add_hline(
                            y=threshold,
                            line_dash="dash",
                            line_color="red",
                            annotation_text=threshold_label.get(st.session_state.language, threshold_label["ru"])
                        )
                        if df.empty:
                            fig.update_yaxes(range=y_range)
                            fig.update_xaxes(range=[datetime.now() - timedelta(minutes=10), datetime.now()])
                        st.plotly_chart(fig, use_container_width=True)
            
            critical_alerts = []
            checks = [
                ("temperature", 1520, ">", titles[0].split(",")[0]),
                ("vibration_level", 4.2, ">", titles[1].split(",")[0]),
                ("cooling_water_flow", 1200, "<", titles[3].split(",")[0]),
                ("casting_speed", 1.8, "<", titles[2].split(",")[0]),
                ("wear_level", 85, ">", titles[4].split(",")[0])
            ]
            
            for key, threshold, op, name in checks:
                if key in sensor_data:
                    val = sensor_data[key]
                    if (op == ">" and val > threshold) or (op == "<" and val < threshold):
                        critical_alerts.append(f"⚠️ {name}: {val:.2f}")
            
            if critical_alerts:
                critical_warning_labels = {
                    "ru": "🚨 КРИТИЧЕСКИЕ ПРЕДУПРЕЖДЕНИЯ:",
                    "en": "🚨 CRITICAL WARNINGS:"
                }
                st.error(critical_warning_labels.get(st.session_state.language, critical_warning_labels["ru"]))
                for alert in critical_alerts:
                    st.markdown(alert)
            
            quality_metrics_labels = {
                "ru": "🎯 Показатели качества",
                "en": "🎯 Quality Metrics"
            }
            st.subheader(quality_metrics_labels.get(st.session_state.language, quality_metrics_labels["ru"]))
            q_cols = st.columns(3)
            
            defects_label = {
                "ru": "Дефекты",
                "en": "Defects"
            }
            
            quality_label = {
                "ru": "Качество",
                "en": "Quality"
            }
            
            speed_label = {
                "ru": "Скорость",
                "en": "Speed"
            }
            
            with q_cols[0]:
                st.metric(defects_label.get(st.session_state.language, defects_label["ru"]), 
                         f"{sensor_data.get('defect_count', 0)} шт" if st.session_state.language == "ru" else f"{sensor_data.get('defect_count', 0)} pcs")
            
            with q_cols[1]:
                quality = sensor_data.get('quality_score', 0)
                st.metric(quality_label.get(st.session_state.language, quality_label["ru"]), f"{quality:.1f}/100")
            
            with q_cols[2]:
                speed = sensor_data.get('casting_speed', 0)
                st.metric(speed_label.get(st.session_state.language, speed_label["ru"]), f"{speed:.2f} м/мин" if st.session_state.language == "ru" else f"{speed:.2f} m/min")
            
            equipment_status_labels = {
                "ru": "🏭 Состояние оборудования",
                "en": "🏭 Equipment Status"
            }
            st.subheader(equipment_status_labels.get(st.session_state.language, equipment_status_labels["ru"]))
            e_cols = st.columns(2)
            
            wear_label = {
                "ru": "Износ",
                "en": "Wear"
            }
            
            status_labels = {
                "ru": ["🟢 Норма", "🟡 Повышенный", "🔴 Критический"],
                "en": ["🟢 Normal", "🟡 Elevated", "🔴 Critical"]
            }
            
            with e_cols[0]:
                wear = sensor_data.get('wear_level', 0)
                if wear < 70:
                    status = status_labels[st.session_state.language][0]
                elif wear < 85:
                    status = status_labels[st.session_state.language][1]
                else:
                    status = status_labels[st.session_state.language][2]
                st.metric(wear_label.get(st.session_state.language, wear_label["ru"]), f"{wear:.1f}%", status)
            
            st.divider()
            historical_analysis_labels = {
                "ru": "Анализ исторических данных",
                "en": "Historical Data Analysis"
            }
            st.subheader(historical_analysis_labels.get(st.session_state.language, historical_analysis_labels["ru"]))
            
            period_label = {
                "ru": "Период",
                "en": "Period"
            }
            
            time_ranges = {
                "ru": ["15 минут", "1 час", "Смена (8 часов)", "Сутки (24 часа)"],
                "en": ["15 minutes", "1 hour", "Shift (8 hours)", "Day (24 hours)"]
            }
            
            time_range = st.selectbox(
                period_label.get(st.session_state.language, period_label["ru"]),
                time_ranges.get(st.session_state.language, time_ranges["ru"]),
                key="time_range_select"
            )
            
            minutes_map = {
                "15 минут": 15, "15 minutes": 15,
                "1 час": 60, "1 hour": 60,
                "Смена (8 часов)": 480, "Shift (8 hours)": 480,
                "Сутки (24 часа)": 1440, "Day (24 hours)": 1440
            }
            
            self.display_historical_data(minutes_map[time_range])
            
        except Exception as e:
            st.error(f"❌ {self.t('error')}: {str(e)}")

    def display_historical_data(self, minutes):
        try:
            time_threshold = datetime.now() - timedelta(minutes=minutes)
            
            column_labels = {
                "ru": [
                    ["Время", "Температура", "Вибрация", "Печь"],
                    ["Время", "Износ", "Статус"],
                    ["Время", "Дефекты", "Качество"]
                ],
                "en": [
                    ["Time", "Temperature", "Vibration", "Furnace"],
                    ["Time", "Wear", "Status"],
                    ["Time", "Defects", "Quality"]
                ]
            }
            
            col_names_list = column_labels.get(st.session_state.language, column_labels["ru"])
            
            queries = [
                ("steel_melting_data", "timestamp, temperature, vibration_level AS vibration, furnace_id", col_names_list[0]),
                ("equipment_status", "timestamp, wear_level, status", col_names_list[1]),
                ("production_quality", "timestamp, defect_count, quality_score", col_names_list[2])
            ]
            
            for table, columns, col_names in queries:
                query = f"SELECT {columns} FROM {table} WHERE timestamp >= %s ORDER BY timestamp"
                
                self.db_manager.cursor.execute(query, (time_threshold,))
                results = self.db_manager.cursor.fetchall()
                
                if results:
                    df = pd.DataFrame(results, columns=col_names)
                    
                    table_title_labels = {
                        "ru": f"### {table.replace('_', ' ').title()} за {minutes} минут",
                        "en": f"### {table.replace('_', ' ').title()} for {minutes} minutes"
                    }
                    st.markdown(table_title_labels.get(st.session_state.language, table_title_labels["ru"]))
                    
                    if table == "steel_melting_data":
                        col1, col2 = st.columns(2)
                        with col1:
                            fig = px.line(df, x=col_names[0], y=col_names[1], color=col_names[3], markers=True)
                            fig.add_hline(y=1520, line_dash="dash", line_color="red")
                            st.plotly_chart(fig, use_container_width=True)
                        with col2:
                            fig = px.line(df, x=col_names[0], y=col_names[2], color=col_names[3], markers=True)
                            fig.add_hline(y=4.2, line_dash="dash", line_color="red")
                            st.plotly_chart(fig, use_container_width=True)
                    
                    elif table == "equipment_status":
                        fig = px.line(df, x=col_names[0], y=col_names[1], color=col_names[2], markers=True)
                        fig.add_hline(y=85, line_dash="dash", line_color="red")
                        st.plotly_chart(fig, use_container_width=True)
                    
                    elif table == "production_quality":
                        col1, col2 = st.columns(2)
                        with col1:
                            fig = px.bar(df, x=col_names[0], y=col_names[1])
                            st.plotly_chart(fig, use_container_width=True)
                        with col2:
                            fig = px.line(df, x=col_names[0], y=col_names[2], markers=True)
                            fig.add_hline(y=80, line_dash="dash", line_color="orange")
                            st.plotly_chart(fig, use_container_width=True)
            
            if not any([self.db_manager.cursor.rowcount > 0 for _ in queries]):
                no_data_labels = {
                    "ru": f"Нет данных за {minutes} минут.",
                    "en": f"No data for {minutes} minutes."
                }
                st.info(no_data_labels.get(st.session_state.language, no_data_labels["ru"]))
                
        except Exception as e:
            st.error(f"❌ {self.t('error')}: {str(e)}")


def main():
    interface = DigitalTwinInterface()

if __name__ == "__main__":
    main()