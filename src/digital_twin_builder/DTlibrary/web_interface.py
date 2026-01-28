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
        if 'casting_speed_history' not in st.session_state:
            st.session_state.casting_speed_history = []
        if 'cooling_water_history' not in st.session_state:
            st.session_state.cooling_water_history = []
        if 'wear_history' not in st.session_state:
            st.session_state.wear_history = []
        if 'quality_history' not in st.session_state:
            st.session_state.quality_history = []
        
        self.setup_ui()

    def setup_ui(self):
        st.set_page_config(page_title="Digital Twin Builder", layout="wide")
        st.title("Digital Twin Builder 🏭")
        
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
            initial_message = """Здравствуйте! Я помогу вам создать цифровой двойник вашего производства. 
            
Расскажите, пожалуйста, о вашем производстве: что именно производится, какие процессы происходят, какое оборудование используется?"""
            
            st.session_state.chat_history.append({"role": "assistant", "content": initial_message})
            st.session_state.interview_completed = False
        
        
        for message in st.session_state.chat_history:
            if message["role"] == "assistant":
                with st.chat_message("assistant"):
                    st.markdown(message["content"])
            else:
                with st.chat_message("user"):
                    st.markdown(message["content"])
        
        if not st.session_state.get('interview_completed', False):
            user_input = st.chat_input("Опишите ваше производство...")
            
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
                    error_msg = f"Произошла ошибка: {str(e)}. Попробуйте переформулировать ваш запрос."
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
                
                st.rerun()
        else:
            st.success("✅ Интервью завершено! Перейдите к следующей вкладке.")
            
            with st.expander("Просмотр собранных требований"):
                st.json(st.session_state.interview_result)
            
            if st.button("Начать новое интервью", key="restart_interview"):
                st.session_state.chat_history = []
                st.session_state.interview_completed = False
                if 'interview_result' in st.session_state:
                    del st.session_state.interview_result
                st.rerun()

    def setup_database_tab(self):
        st.header("Настройка базы данных")
        
        if 'interview_result' not in st.session_state:
            st.warning("⚠️ Пожалуйста, завершите интервью на вкладке 'Интервью с пользователем'")
            return
        
        st.subheader("Описание системы")
        st.info(json.dumps(st.session_state.interview_result, ensure_ascii=False, indent=2))
        
        if 'db_schema' not in st.session_state:
            if st.button("🔨 Сгенерировать схему БД", key="generate_schema_btn"):
                with st.spinner("Генерация схемы базы данных..."):
                    try:
                        schema = self.db_agent.run(st.session_state.interview_result)
                        st.session_state.db_schema = schema
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка генерации схемы: {str(e)}")
            return
        
        st.subheader("Сгенерированная схема базы данных")
        st.json(st.session_state.db_schema, expanded=True)
        
        if st.button("📖 Получить описание схемы", key="interpret_schema_btn"):
            with st.spinner("Генерация описания..."):
                try:
                    interpretation = self.db_agent.interpret_schema(st.session_state.db_schema)
                    st.markdown("### Описание схемы БД")
                    st.write(interpretation)
                except Exception as e:
                    st.error(f"Ошибка интерпретации: {str(e)}")
        
        st.success("✅ Схема базы данных успешно сгенерирована!")
        
        st.subheader("Управление данными")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📊 Сгенерировать тестовые данные (7 дней)", key="generate_test_data_btn"):
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
                        st.success("✅ Тестовые данные успешно сгенерированы!")
                    else:
                        st.error("❌ Ошибка генерации тестовых данных")
                except Exception as e:
                    st.error(f"❌ Ошибка: {str(e)}")
        
        with col2:
            if st.button("🗑️ Очистить все данные", key="clear_data_btn", type="secondary"):
                try:
                    db_manager = DatabaseManager(
                        dbname="digital_twin",
                        user="postgres",
                        password="omgssmyalg",
                    )
                    db_manager.cursor.execute("TRUNCATE TABLE steel_melting_data, equipment_status, production_quality CASCADE")
                    db_manager.conn.commit()
                    db_manager.close()
                    st.success("✅ Все данные успешно удалены!")
                except Exception as e:
                    st.error(f"❌ Ошибка: {str(e)}")
        
        if st.button("💾 Сохранить схему и продолжить", key="db_continue_btn"):
            st.session_state.db_configured = True
            st.success("Схема сохранена!")
            st.rerun()

    def setup_twin_tab(self):
        st.header("Конфигурация цифрового двойника")
        
        if 'db_schema' not in st.session_state:
            st.warning("⚠️ Пожалуйста, завершите настройку базы данных")
            return
        
        st.subheader("Схема базы данных")
        with st.expander("Посмотреть схему БД"):
            st.json(st.session_state.db_schema)
        
        if 'twin_config' not in st.session_state:
            if st.button("⚙️ Сгенерировать конфигурацию", key="generate_config_btn"):
                with st.spinner("Генерация конфигурации..."):
                    try:
                        config = self.dt_agent.generate_configuration(
                            st.session_state.interview_result,
                            st.session_state.db_schema
                        )
                        st.session_state.twin_config = config
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка: {str(e)}")
            return
        
        st.subheader("Конфигурация цифрового двойника")
        st.json(st.session_state.twin_config, expanded=True)
        
        st.subheader("Код симуляции PyChrono")
        
        if 'simulation_code' not in st.session_state:
            if st.button("🔧 Сгенерировать код", key="generate_sim_btn"):
                with st.spinner("Генерация кода..."):
                    try:
                        sim_code = self.dt_agent.generate_simulation_code(
                            st.session_state.interview_result,
                            st.session_state.db_schema
                        )
                        st.session_state.simulation_code = sim_code
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка: {str(e)}")
        
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
                    try:
                        db_code = self.dt_agent.generate_database_code(st.session_state.db_schema)
                        st.session_state.database_code = db_code
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка: {str(e)}")
        
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
        
        st.divider()
        st.subheader("🚀 Запуск цифрового двойника")
        
        mode = st.radio(
            "Режим сенсоров", 
            ["Симуляция", "Реальное оборудование"],
            key="sensor_mode_radio"
        )
        sensor_mode = 'sim' if mode == "Симуляция" else 'real'
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("▶️ Запустить", key="start_twin_btn", type="primary"):
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
                    st.success("✅ Цифровой двойник запущен!")
                except Exception as e:
                    st.error(f"❌ Ошибка: {str(e)}")
        
        with col2:
            if st.button(
                "⏹️ Остановить",
                disabled=not st.session_state.get('sensor_running', False),
                key="stop_twin_btn"
            ):
                if self.sensor_manager:
                    self.sensor_manager.stop()
                if self.db_manager:
                    self.db_manager.close()
                st.session_state.sensor_running = False
                st.success("⏹️ Остановлено")

    def setup_sensor_tab(self):
        st.header("Панель мониторинга")
        
        if not st.session_state.get('sensor_running', False):
            st.warning("⚠️ Цифровой двойник не запущен. Запустите его на вкладке 'Цифровой двойник'.")
            return
        
        
        if self.sensor_manager is None:
            try:
                current_mode = st.session_state.get('sensor_mode', 'sim')
                self.sensor_manager = SensorManager(mode=current_mode)
                self.sensor_manager.start()
            except Exception as e:
                st.error(f"Ошибка инициализации сенсоров: {str(e)}")
                return
        
        if self.db_manager is None:
            try:
                self.db_manager = DatabaseManager(
                    dbname="digital_twin",
                    user="postgres",
                    password="omgssmyalg"
                )
            except Exception as e:
                st.error(f"Ошибка подключения к БД: {str(e)}")
                return
        
        
        current_mode = st.session_state.get('sensor_mode', 'sim')
        new_mode = st.radio(
            "Режим сенсоров",
            ["Симуляция", "Реальное оборудование"],
            index=0 if current_mode == 'sim' else 1,
            key="sensor_toggle_radio"
        )
        
        if (new_mode == "Симуляция" and current_mode != 'sim') or \
           (new_mode == "Реальное оборудование" and current_mode == 'sim'):
            try:
                self.sensor_manager.set_mode('sim' if new_mode == "Симуляция" else 'real')
                st.session_state.sensor_mode = 'sim' if new_mode == "Симуляция" else 'real'
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка смены режима: {str(e)}")
                return
        
        try:
            data = self.sensor_manager.get_data()
            if data:
                
                if self.db_manager:
                    try:
                        self.db_manager.store_sensor_data(data)
                    except Exception as e:
                        st.error(f"Ошибка сохранения: {str(e)}")
                
                sensor_data = data["sensor_data"]
                
                display_data = []
                for key, value in sensor_data.items():
                    if isinstance(value, (int, float)):
                        display_data.append({
                            "Параметр": key.replace("_", " ").title(),
                            "Значение": f"{value:.2f}" if isinstance(value, float) else str(value)
                        })
                    else:
                        display_data.append({
                            "Параметр": key.replace("_", " ").title(),
                            "Значение": str(value)
                        })
                
                st.subheader("Текущие показания")
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
                
                
                st.subheader("Графики в реальном времени")
                
                graphs = [
                    ("temperature_history", "Температура стали, °C", 1520, [1500, 1600]),
                    ("vibration_history", "Вибрация, м/с²", 4.2, [0, 10]),
                    ("casting_speed_history", "Скорость разливки, м/мин", 1.8, [0, 3]),
                    ("cooling_water_history", "Расход воды, л/мин", 1200, [1000, 1500]),
                    ("wear_history", "Износ оборудования, %", 85, [0, 100]),
                    ("quality_history", "Качество продукции", 80, [0, 100])
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
                                labels={"value": "Значение", "timestamp": "Время"},
                                height=300
                            )
                            fig.add_hline(
                                y=threshold,
                                line_dash="dash",
                                line_color="red",
                                annotation_text="Порог"
                            )
                            if df.empty:
                                fig.update_yaxes(range=y_range)
                                fig.update_xaxes(range=[datetime.now() - timedelta(minutes=10), datetime.now()])
                            st.plotly_chart(fig, use_container_width=True)
                
                critical_alerts = []
                checks = [
                    ("temperature", 1520, ">", "Температура"),
                    ("vibration_level", 4.2, ">", "Вибрация"),
                    ("cooling_water_flow", 1200, "<", "Расход воды"),
                    ("casting_speed", 1.8, "<", "Скорость"),
                    ("wear_level", 85, ">", "Износ")
                ]
                
                for key, threshold, op, name in checks:
                    if key in sensor_data:
                        val = sensor_data[key]
                        if (op == ">" and val > threshold) or (op == "<" and val < threshold):
                            critical_alerts.append(f"⚠️ {name}: {val:.2f}")
                
                if critical_alerts:
                    st.error("🚨 КРИТИЧЕСКИЕ ПРЕДУПРЕЖДЕНИЯ:")
                    for alert in critical_alerts:
                        st.markdown(alert)
                
                
                st.subheader("🎯 Показатели качества")
                q_cols = st.columns(3)
                
                with q_cols[0]:
                    st.metric("Дефекты", f"{sensor_data.get('defect_count', 0)} шт")
                
                with q_cols[1]:
                    quality = sensor_data.get('quality_score', 0)
                    st.metric("Качество", f"{quality:.1f}/100")
                
                with q_cols[2]:
                    speed = sensor_data.get('casting_speed', 0)
                    st.metric("Скорость", f"{speed:.2f} м/мин")
                
                
                st.subheader("🏭 Состояние оборудования")
                e_cols = st.columns(2)
                
                with e_cols[0]:
                    wear = sensor_data.get('wear_level', 0)
                    if wear < 70:
                        status = "🟢 Норма"
                    elif wear < 85:
                        status = "🟡 Повышенный"
                    else:
                        status = "🔴 Критический"
                    st.metric("Износ", f"{wear:.1f}%", status)
                
                
                st.divider()
                st.subheader("Анализ исторических данных")
                
                time_range = st.selectbox(
                    "Период",
                    ["15 минут", "1 час", "Смена (8 часов)", "Сутки (24 часа)"],
                    key="time_range_select"
                )
                
                minutes_map = {
                    "15 минут": 15,
                    "1 час": 60,
                    "Смена (8 часов)": 480,
                    "Сутки (24 часа)": 1440
                }
                
                self.display_historical_data(minutes_map[time_range])
                
        except Exception as e:
            st.error(f"❌ Ошибка: {str(e)}")

    def display_historical_data(self, minutes):
        try:
            time_threshold = datetime.now() - timedelta(minutes=minutes)
            
            queries = [
                ("steel_melting_data", "timestamp, temperature, vibration_level AS vibration, furnace_id", ["Время", "Температура", "Вибрация", "Печь"]),
                ("equipment_status", "timestamp, wear_level, status", ["Время", "Износ", "Статус"]),
                ("production_quality", "timestamp, defect_count, quality_score", ["Время", "Дефекты", "Качество"])
            ]
            
            for table, columns, col_names in queries:
                query = f"SELECT {columns} FROM {table} WHERE timestamp >= %s ORDER BY timestamp"
                
                self.db_manager.cursor.execute(query, (time_threshold,))
                results = self.db_manager.cursor.fetchall()
                
                if results:
                    df = pd.DataFrame(results, columns=col_names)
                    
                    st.markdown(f"### {table.replace('_', ' ').title()} за {minutes} минут")
                    
                    if table == "steel_melting_data":
                        col1, col2 = st.columns(2)
                        with col1:
                            fig = px.line(df, x="Время", y="Температура", color="Печь", markers=True)
                            fig.add_hline(y=1520, line_dash="dash", line_color="red")
                            st.plotly_chart(fig, use_container_width=True)
                        with col2:
                            fig = px.line(df, x="Время", y="Вибрация", color="Печь", markers=True)
                            fig.add_hline(y=4.2, line_dash="dash", line_color="red")
                            st.plotly_chart(fig, use_container_width=True)
                    
                    elif table == "equipment_status":
                        fig = px.line(df, x="Время", y="Износ", color="Статус", markers=True)
                        fig.add_hline(y=85, line_dash="dash", line_color="red")
                        st.plotly_chart(fig, use_container_width=True)
                    
                    elif table == "production_quality":
                        col1, col2 = st.columns(2)
                        with col1:
                            fig = px.bar(df, x="Время", y="Дефекты")
                            st.plotly_chart(fig, use_container_width=True)
                        with col2:
                            fig = px.line(df, x="Время", y="Качество", markers=True)
                            fig.add_hline(y=80, line_dash="dash", line_color="orange")
                            st.plotly_chart(fig, use_container_width=True)
            
            if not any([self.db_manager.cursor.rowcount > 0 for _ in queries]):
                st.info(f"Нет данных за {minutes} минут.")
                
        except Exception as e:
            st.error(f"❌ Ошибка: {str(e)}")


def main():
    interface = DigitalTwinInterface()

if __name__ == "__main__":
    main()