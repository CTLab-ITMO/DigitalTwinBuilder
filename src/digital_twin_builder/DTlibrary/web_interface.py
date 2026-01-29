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
        try:
            self.ui_agent = UserInteractionAgent(language=st.session_state.language)
        except TypeError:
            self.ui_agent = UserInteractionAgent()
            
        try:
            self.db_agent = DatabaseAgent(language=st.session_state.language)
        except TypeError:
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
                try:
                    self.ui_agent.set_language(selected_language)
                except (AttributeError, TypeError):
                    pass
                try:
                    self.db_agent.set_language(selected_language)
                except (AttributeError, TypeError):
                    pass
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
                    error_msg = f"{self.t('error')}: {str(e)}. " + (
                        "Попробуйте переформулировать ваш запрос." if st.session_state.language == "ru" 
                        else "Please try to rephrase your request."
                    )
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})

                st.rerun()
        else:
            st.success(self.t("interview_completed"))

            with st.expander(self.t("view_requirements")):
                st.json(st.session_state.interview_result)

            if st.button(self.t("restart_interview"), key="restart_interview"):
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

        st.subheader(self.t("system_description"))
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

        st.subheader(self.t("generated_schema"))
        st.json(st.session_state.db_schema, expanded=True)

        if st.button(self.t("get_schema_description"), key="interpret_schema_btn"):
            with st.spinner(self.t("generating_schema")):
                try:
                    interpretation = self.db_agent.interpret_schema(st.session_state.db_schema)
                    st.markdown(self.t("schema_description_title"))
                    st.write(interpretation)
                except Exception as e:
                    st.error(f"{self.t('interpretation_error')}: {str(e)}")

        st.success(self.t("schema_generated_success"))

        st.subheader(self.t("data_management"))

        col1, col2 = st.columns(2)

        with col1:
            if st.button(self.t("generate_test_data"), key="generate_test_data_btn"):
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
                        st.success(self.t("test_data_success"))
                    else:
                        st.error(self.t("test_data_error"))
                except Exception as e:
                    st.error(f"❌ {self.t('error')}: {str(e)}")

        with col2:
            if st.button(self.t("clear_data"), key="clear_data_btn", type="secondary"):
                try:
                    db_manager = DatabaseManager(
                        dbname="digital_twin",
                        user="postgres",
                        password="omgssmyalg",
                    )
                    db_manager.cursor.execute("TRUNCATE TABLE steel_melting_data, equipment_status, production_quality CASCADE")
                    db_manager.conn.commit()
                    db_manager.close()
                    st.success(self.t("data_cleared"))
                except Exception as e:
                    st.error(f"❌ {self.t('error')}: {str(e)}")

        if st.button(self.t("save_schema"), key="db_continue_btn"):
            st.session_state.db_configured = True
            st.success(self.t("schema_saved"))
            st.rerun()

    def setup_twin_tab(self):
        st.header(self.t("dt_header"))

        if 'db_schema' not in st.session_state:
            st.warning(self.t("schema_not_ready"))
            return

        st.subheader(self.t("dt_schema"))
        with st.expander(self.t("view_schema")):
            st.json(st.session_state.db_schema)

        if 'twin_config' not in st.session_state:
            if st.button(self.t("generate_config_button"), key="generate_config_btn"):
                with st.spinner(self.t("generating_config")):
                    try:
                        config = self.dt_agent.generate_configuration(
                            st.session_state.interview_result,
                            st.session_state.db_schema
                        )
                        st.session_state.twin_config = config
                        st.rerun()
                    except Exception as e:
                        st.error(f"{self.t('error')}: {str(e)}")
            return

        st.subheader(self.t("dt_config_title"))
        st.json(st.session_state.twin_config, expanded=True)

        st.subheader(self.t("simulation_code_title"))

        if 'simulation_code' not in st.session_state:
            if st.button(self.t("generate_code_button"), key="generate_sim_btn"):
                with st.spinner(self.t("generating_code")):
                    try:
                        sim_code = self.dt_agent.generate_simulation_code(
                            st.session_state.interview_result,
                            st.session_state.db_schema
                        )
                        st.session_state.simulation_code = sim_code
                        st.rerun()
                    except Exception as e:
                        st.error(f"{self.t('error')}: {str(e)}")

        if 'simulation_code' in st.session_state:
            with st.expander(self.t("view_code")):
                st.code(st.session_state.simulation_code, language="python")

            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    self.t("download_code"),
                    st.session_state.simulation_code,
                    "simulation.py",
                    "text/x-python",
                    key="download_sim"
                )
            with col2:
                if st.button(self.t("regenerate_button"), key="regen_sim"):
                    del st.session_state.simulation_code
                    st.rerun()

        st.subheader(self.t("database_sql_title"))

        if 'database_code' not in st.session_state:
            if st.button(self.t("generate_sql_button"), key="generate_sql_btn"):
                with st.spinner(self.t("generating_sql")):
                    try:
                        db_code = self.dt_agent.generate_database_code(st.session_state.db_schema)
                        st.session_state.database_code = db_code
                        st.rerun()
                    except Exception as e:
                        st.error(f"{self.t('error')}: {str(e)}")

        if 'database_code' in st.session_state:
            with st.expander(self.t("view_sql")):
                st.code(st.session_state.database_code, language="sql")

            st.download_button(
                self.t("download_sql"),
                st.session_state.database_code,
                "schema.sql",
                "text/plain",
                key="download_sql"
            )

        st.divider()
        st.subheader(self.t("run_dt_title"))

        mode_options = ["Симуляция", "Реальное оборудование"] if st.session_state.language == "ru" else ["Simulation", "Real Equipment"]

        mode = st.radio(
            self.t("sensor_mode_label"),
            mode_options,
            key="sensor_mode_radio"
        )
        sensor_mode = 'sim' if mode in ["Симуляция", "Simulation"] else 'real'

        col1, col2 = st.columns(2)

        with col1:
            if st.button(self.t("start_button"), key="start_twin_btn"):
                try:
                    self.sensor_manager = SensorManager(mode=sensor_mode)
                    self.sensor_manager.start()

                    self.db_manager = DatabaseManager(
                        dbname="digital_twin",
                        user="postgres",
                        password="omgssmyalg"
                    )
                    self.db_manager.create_sensor_tables()

                    st.session_state.sensor_running = True
                    st.session_state.sensor_mode = sensor_mode
                    st.success(self.t("dt_started"))
                except Exception as e:
                    st.error(f"❌ {self.t('error')}: {str(e)}")

        with col2:
            if st.button(
                self.t("stop_button"),
                disabled=not st.session_state.get('sensor_running', False),
                key="stop_twin_btn"
            ):
                if self.sensor_manager:
                    self.sensor_manager.stop()
                if self.db_manager:
                    self.db_manager.close()
                st.session_state.sensor_running = False
                st.success(self.t("dt_stopped"))

    def setup_sensor_tab(self):
        st.header(self.t("sensors_header"))

        if not st.session_state.get('sensor_running', False):
            st.warning(self.t("sensors_not_running"))
            return

        if self.sensor_manager is None:
            try:
                current_mode = st.session_state.get('sensor_mode', 'sim')
                self.sensor_manager = SensorManager(mode=current_mode)
                self.sensor_manager.start()
            except Exception as e:
                st.error(f"{self.t('error')} {self.t('initializing_sensors')}: {str(e)}")
                return

        if self.db_manager is None:
            try:
                self.db_manager = DatabaseManager(
                    dbname="digital_twin",
                    user="postgres",
                    password="omgssmyalg"
                )
            except Exception as e:
                st.error(f"{self.t('error')} {self.t('connecting_to_db')}: {str(e)}")
                return

        current_mode = st.session_state.get('sensor_mode', 'sim')
        mode_options = ["Симуляция", "Реальное оборудование"] if st.session_state.language == "ru" else ["Simulation", "Real Equipment"]

        new_mode = st.radio(
            self.t("sensor_mode_label"),
            mode_options,
            index=0 if current_mode == 'sim' else 1,
            key="sensor_toggle_radio"
        )

        internal_new_mode = 'sim' if new_mode in ["Симуляция", "Simulation"] else 'real'
        
        if internal_new_mode != current_mode:
            try:
                self.sensor_manager.set_mode(internal_new_mode)
                st.session_state.sensor_mode = internal_new_mode
                st.rerun()
            except Exception as e:
                st.error(f"{self.t('error')} {self.t('changing_mode')}: {str(e)}")
                return

        try:
            data = self.sensor_manager.get_data()
            if data:
                if self.db_manager:
                    try:
                        self.db_manager.store_sensor_data(data)
                    except Exception as e:
                        st.error(f"{self.t('error')} {self.t('saving_data')}: {str(e)}")

                sensor_data = data["sensor_data"]

                display_data = []
                for key, value in sensor_data.items():
                    if isinstance(value, (int, float)):
                        display_data.append({
                            self.t("parameter_col"): key.replace("_", " ").title(),
                            self.t("value_col"): f"{value:.2f}" if isinstance(value, float) else str(value)
                        })
                    else:
                        display_data.append({
                            self.t("parameter_col"): key.replace("_", " ").title(),
                            self.t("value_col"): str(value)
                        })

                st.subheader(self.t("current_readings"))
                st.dataframe(pd.DataFrame(display_data), use_container_width=True)

                current_time = datetime.fromtimestamp(data["timestamp"])

                for hist_key, sensor_key in [
                    ('temperature_history', 'temperature'),
                    ('vibration_history', 'vibration_level'),
                    ('casting_speed_history', 'casting_speed'),
                    ('cooling_water_history', 'cooling_water_flow'),
                    ('wear_history', 'wear_level'),
                    ('quality_history', 'quality_score')
                ]:
                    if sensor_key in sensor_data:
                        history = st.session_state.get(hist_key, [])
                        history.append({"timestamp": current_time, "value": sensor_data[sensor_key]})
                        if len(history) > 100:
                            history = history[-100:]
                        st.session_state[hist_key] = history

                st.subheader(self.t("realtime_charts"))

                if st.session_state.language == "ru":
                    chart_titles = [
                        "Температура стали, °C",
                        "Вибрация, м/с²",
                        "Скорость разливки, м/мин",
                        "Расход воды, л/мин",
                        "Износ оборудования, %",
                        "Качество продукции"
                    ]
                else:
                    chart_titles = [
                        "Steel Temperature, °C",
                        "Vibration, m/s²",
                        "Casting Speed, m/min",
                        "Water Flow, l/min",
                        "Equipment Wear, %",
                        "Product Quality"
                    ]

                graphs = [
                    ("temperature_history", chart_titles[0], 1520, [1500, 1600]),
                    ("vibration_history", chart_titles[1], 4.2, [0, 10]),
                    ("casting_speed_history", chart_titles[2], 1.8, [0, 3]),
                    ("cooling_water_history", chart_titles[3], 1200, [1000, 1500]),
                    ("wear_history", chart_titles[4], 85, [0, 100]),
                    ("quality_history", chart_titles[5], 80, [0, 100])
                ]

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
                                    "value": self.t("value_col"),
                                    "timestamp": self.t("time_col")
                                },
                                height=300
                            )
                            fig.add_hline(
                                y=threshold,
                                line_dash="dash",
                                line_color="red",
                                annotation_text=self.t("threshold")
                            )
                            if df.empty:
                                fig.update_yaxes(range=y_range)
                                fig.update_xaxes(range=[datetime.now() - timedelta(minutes=10), datetime.now()])
                            st.plotly_chart(fig, use_container_width=True)

                critical_alerts = []
                checks = [
                    ("temperature", 1520, ">", self.t("temperature_label")),
                    ("vibration_level", 4.2, ">", self.t("vibration_label")),
                    ("cooling_water_flow", 1200, "<", self.t("water_flow_label")),
                    ("casting_speed", 1.8, "<", self.t("casting_speed_label")),
                    ("wear_level", 85, ">", self.t("wear_label"))
                ]

                for key, threshold, op, name in checks:
                    if key in sensor_data:
                        val = sensor_data[key]
                        if (op == ">" and val > threshold) or (op == "<" and val < threshold):
                            critical_alerts.append(f"⚠️ {name}: {val:.2f}")

                if critical_alerts:
                    st.error(self.t("critical_warnings"))
                    for alert in critical_alerts:
                        st.markdown(alert)

                st.subheader(self.t("quality_metrics"))
                q_cols = st.columns(3)

                with q_cols[0]:
                    defects_unit = " шт" if st.session_state.language == "ru" else " pcs"
                    st.metric(self.t("defects_label"), f"{sensor_data.get('defect_count', 0)}{defects_unit}")

                with q_cols[1]:
                    quality = sensor_data.get('quality_score', 0)
                    st.metric(self.t("quality_label"), f"{quality:.1f}/100")

                with q_cols[2]:
                    speed = sensor_data.get('casting_speed', 0)
                    speed_unit = " м/мин" if st.session_state.language == "ru" else " m/min"
                    st.metric(self.t("speed_label"), f"{speed:.2f}{speed_unit}")

                st.subheader(self.t("equipment_status"))
                e_cols = st.columns(2)

                with e_cols[0]:
                    wear = sensor_data.get('wear_level', 0)
                    if wear < 70:
                        status = self.t("wear_normal")
                    elif wear < 85:
                        status = self.t("wear_elevated")
                    else:
                        status = self.t("wear_critical")
                    st.metric(self.t("wear_metric"), f"{wear:.1f}%", status)

                st.divider()
                st.subheader(self.t("historical_analysis"))

                if st.session_state.language == "ru":
                    time_range_options = ["15 минут", "1 час", "Смена (8 часов)", "Сутки (24 часа)"]
                else:
                    time_range_options = ["15 minutes", "1 hour", "Shift (8 hours)", "Day (24 hours)"]

                time_range = st.selectbox(
                    self.t("time_period"),
                    time_range_options,
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

            if st.session_state.language == "ru":
                col_names_list = [
                    ["Время", "Температура", "Вибрация", "Печь"],
                    ["Время", "Износ", "Статус"],
                    ["Время", "Дефекты", "Качество"]
                ]
            else:
                col_names_list = [
                    ["Time", "Temperature", "Vibration", "Furnace"],
                    ["Time", "Wear", "Status"],
                    ["Time", "Defects", "Quality"]
                ]

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

                    table_name = table.replace('_', ' ').title()
                    st.markdown(f"### {table_name} {self.t('for_last')} {minutes} {self.t('minutes_label')}")

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
                st.info(f"{self.t('no_data_for_period')} {minutes} {self.t('minutes_label')}.")

        except Exception as e:
            st.error(f"❌ {self.t('error')}: {str(e)}")


def main():
    interface = DigitalTwinInterface()

if __name__ == "__main__":
    main()