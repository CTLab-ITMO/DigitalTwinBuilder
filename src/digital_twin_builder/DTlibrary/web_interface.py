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
            initial_message = """Здравствуйте! Для построения цифрового двойника производства, пожалуйста, предоставьте следующую информацию:
            
            1. Основные характеристики объекта
            2. Цели и задачи цифрового двойника
            3. Доступные данные и источники информации
            4. Временные рамки и частота обновления данных
            5. Особые требования или ограничения
            
            Пожалуйста, начните с описания вашего производства."""
            
            st.session_state.chat_history.append({"role": "bot", "content": initial_message})
            st.session_state.interview_completed = False
        
        for message in st.session_state.chat_history:
            if message["role"] == "bot":
                with st.chat_message("assistant"):
                    st.markdown(message["content"])
            else:
                with st.chat_message("user"):
                    st.markdown(message["content"])
        
        if not st.session_state.get('interview_completed', False):
            user_input = st.chat_input("Опишите ваше металлургическое производство...")
            
            if user_input:
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                
                st.session_state.interview_result = {
                    "system_description": user_input,
                    "status": "completed"
                }
                
                bot_response = "Благодарю за подробное описание! На основе этой информации мы создадим цифровой двойник вашего металлургического производства. Теперь перейдите к вкладке 'Database Configuration' для настройки базы данных."
                st.session_state.chat_history.append({"role": "bot", "content": bot_response})
                st.session_state.interview_completed = True
                
                st.rerun()
        else:
            st.success("Интервью завершено! Перейдите к следующей вкладке.")
            
            with st.expander("Просмотр сохраненных данных"):
                st.write(st.session_state.interview_result)

    def setup_database_tab(self):
        st.header("Настройка базы данных")
        
        if 'interview_result' not in st.session_state:
            st.warning("Пожалуйста, завершите интервью на вкладке 'Интервью с пользователем'")
            return
        
        example_schema = {
            "tables": [
                {
                    "name": "sensor_data",
                    "columns": [
                        {"name": "id", "type": "SERIAL", "constraints": "PRIMARY KEY"},
                        {"name": "timestamp", "type": "TIMESTAMP", "constraints": "NOT NULL"},
                        {"name": "furnace_id", "type": "VARCHAR(20)"},
                        {"name": "temperature", "type": "FLOAT"},
                        {"name": "power_consumption", "type": "FLOAT"},
                        {"name": "vibration_level", "type": "FLOAT"},
                        {"name": "chemical_composition", "type": "JSON"}
                    ]
                },
                {
                    "name": "equipment_status",
                    "columns": [
                        {"name": "id", "type": "SERIAL", "constraints": "PRIMARY KEY"},
                        {"name": "timestamp", "type": "TIMESTAMP", "constraints": "NOT NULL"},
                        {"name": "equipment_type", "type": "VARCHAR(50)"},
                        {"name": "status", "type": "VARCHAR(20)"},
                        {"name": "wear_level", "type": "FLOAT"},
                        {"name": "maintenance_due", "type": "DATE"}
                    ]
                },
                {
                    "name": "production_quality",
                    "columns": [
                        {"name": "id", "type": "SERIAL", "constraints": "PRIMARY KEY"},
                        {"name": "batch_id", "type": "VARCHAR(30)"},
                        {"name": "steel_grade", "type": "VARCHAR(20)"},
                        {"name": "defect_count", "type": "INTEGER"},
                        {"name": "quality_score", "type": "FLOAT"}
                    ]
                }
            ],
            "relationships": [
                "FOREIGN KEY (furnace_id) REFERENCES equipment_status(id)",
                "FOREIGN KEY (batch_id) REFERENCES production_quality(id)"
            ]
        }
        
        if 'db_schema' not in st.session_state:
            st.session_state.db_schema = example_schema
        
        st.subheader("Описание системы")
        st.info(st.session_state.interview_result["system_description"])
        
        st.subheader("Сгенерированная схема базы данных")
        st.json(example_schema, expanded=True)
        
        st.success("Схема базы данных успешно сгенерирована! Теперь вы можете перейти к настройке цифрового двойника.")
        
        with st.expander("Визуальное представление схемы"):
            st.markdown("""
            ### Структура базы данных для металлургического производства
            
            **1. Таблица steel_melting_data (данные плавки):**
            - `timestamp`: Временная метка измерения
            - `furnace_id`: Идентификатор печи
            - `temperature`: Температура в печи (°C)
            - `power_consumption`: Потребляемая мощность (кВт)
            - `vibration_level`: Уровень вибрации оборудования
            - `chemical_composition`: Химический состав стали (JSON)
            
            **2. Таблица equipment_status (состояние оборудования):**
            - `timestamp`: Временная метка измерения
            - `equipment_type`: Тип оборудования (печь, конвейер и т.д.)
            - `status`: Текущий статус (работает, остановлено, обслуживание)
            - `wear_level`: Уровень износа (0-1)
            - `maintenance_due`: Дата следующего обслуживания
            
            **3. Таблица production_quality (качество продукции):**
            - `batch_id`: Идентификатор партии
            - `steel_grade`: Марка стали
            - `defect_count`: Количество дефектов
            - `quality_score`: Общая оценка качества (0-100%)
            
            **Связи:**
            - Плавки связаны с оборудованием через furnace_id
            - Партии продукции связаны с данными плавки через batch_id
            """)
        
        if st.button("Сохранить схему и продолжить", key="db_continue_btn"):
            st.session_state.db_configured = True
            st.rerun()
        
        st.subheader("Управление данными")
    
        # Кнопка для генерации тестовых данных
        if st.button("Сгенерировать тестовые данные (7 дней)", key="generate_test_data_btn"):
            try:
                # Создаем временное подключение
                db_manager = DatabaseManager(
                    dbname="digital_twin",
                    user="postgres",
                    password="omgssmyalg",
                    host="localhost",
                    port="5432"
                )
                # Создаем таблицы перед генерацией данных
                db_manager.create_sensor_tables()

                success = db_manager.generate_test_data()
                db_manager.close()
                
                if success:
                    st.success("Тестовые данные успешно сгенерированы!")
                else:
                    st.error("Ошибка генерации тестовых данных")
            except Exception as e:
                st.error(f"Ошибка подключения к базе данных: {str(e)}")
        
        # Кнопка для очистки данных
        if st.button("Очистить все данные", key="clear_data_btn", type="secondary"):
            try:
                db_manager = DatabaseManager(
                    dbname="digital_twin",
                    user="postgres",
                    password="omgssmyalg",
                )
                db_manager.cursor.execute("TRUNCATE TABLE steel_melting_data, equipment_status, production_quality CASCADE")
                db_manager.conn.commit()
                db_manager.close()
                st.success("Все данные успешно удалены!")
            except Exception as e:
                st.error(f"Ошибка очистки данных: {str(e)}")

    def setup_twin_tab(self):
        st.header("Конфигурация цифрового двойника")
        
        if 'db_schema' not in st.session_state:
            st.warning("Пожалуйста, завершите настройку базы данных на предыдущей вкладке")
            return
        
        exact_config = {
            "components": [
                {
                    "name": "crystallizer_monitoring",
                    "type": "data_collection",
                    "sensors": ["temperature", "casting_speed", "cooling_water_flow", "vibration"]
                },
                {
                    "name": "slab_quality_analysis",
                    "type": "analytics",
                    "analytics": [
                        "defect_prediction",
                        "crystallization_quality",
                        "chemical_composition_analysis"
                    ]
                },
                {
                    "name": "equipment_wear_analysis",
                    "type": "ml_module",
                    "models": [
                        "crystallizer_wear_prediction",
                        "roller_wear_estimation",
                        "maintenance_optimization"
                    ]
                },
                {
                    "name": "casting_control_dashboard",
                    "type": "visualization",
                    "widgets": [
                        "realtime_temperature_chart",
                        "casting_speed_optimizer",
                        "cooling_water_flow_monitor",
                        "vibration_analysis",
                        "slab_quality_metrics",
                        "equipment_health_status"
                    ]
                }
            ],
            "data_flows": [
                {
                    "from": "crystallizer_monitoring",
                    "to": "database",
                    "protocol": "OPC-UA",
                    "frequency": "3s"
                },
                {
                    "from": "database",
                    "to": "slab_quality_analysis",
                    "protocol": "gRPC",
                    "frequency": "10s"
                },
                {
                    "from": "database",
                    "to": "equipment_wear_analysis",
                    "protocol": "REST",
                    "frequency": "hourly"
                },
                {
                    "from": "slab_quality_analysis",
                    "to": "casting_control_dashboard",
                    "protocol": "WebSocket",
                    "frequency": "realtime"
                }
            ],
            "visualization": {
                "layout": "continuous_casting_operator",
                "refresh_rate": 3000,
                "alerts": [
                    {"parameter": "crystallizer_temperature", "threshold": 1520, "condition": ">"},
                    {"parameter": "casting_speed", "threshold": 1.8, "condition": "<"},
                    {"parameter": "cooling_water_flow", "threshold": 1200, "condition": "<"},
                    {"parameter": "vibration_level", "threshold": 4.2, "condition": ">"}
                ],
                "kpis": [
                    "slab_defect_rate",
                    "casting_speed_efficiency",
                    "equipment_uptime",
                    "cooling_water_usage_per_ton"
                ]
            }
        }
        
        if 'twin_config' not in st.session_state:
            st.session_state.twin_config = exact_config
        
        st.subheader("Схема базы данных")
        st.json(st.session_state.db_schema, expanded=False)
        
        st.subheader("Конфигурация цифрового двойника")
        st.json(exact_config, expanded=True)
        
        with st.expander("Детальное описание компонентов цифрового двойника"):
            st.markdown("""
            ### Компоненты системы для участка непрерывной разливки стали:
            
            **1. Мониторинг кристаллизатора (crystallizer_monitoring):**
            - Сбор данных с термопар: температура стали в кристаллизаторе
            - Контроль скорости разливки с датчиков валков
            - Мониторинг расхода охлаждающей воды
            - Анализ вибрации оборудования
            - Частота обновления: 3 секунды
            
            **2. Анализ качества слябов (slab_quality_analysis):**
            - Прогнозирование дефектов (раковины, трещины)
            - Оценка качества кристаллизации
            - Анализ химического состава стали
            - Интеграция с лабораторными данными
            
            **3. Анализ износа оборудования (equipment_wear_analysis):**
            - Прогнозирование износа кристаллизатора
            - Оценка состояния тянущих валков
            - Оптимизация графика техобслуживания
            - Рекомендации по замене компонентов
            
            **4. Панель управления разливкой (casting_control_dashboard):**
            - Визуализация температуры стали в реальном времени
            - Оптимизатор скорости разливки
            - Мониторинг расхода охлаждающей воды
            - Анализ вибрации валков
            - Показатели качества слябов
            - Статус износа оборудования
            """)
        
        mode = st.radio("Режим работы сенсоров", 
                    ["Симуляция", "Реальное оборудование"], 
                    index=0,
                    key="sensor_mode_radio")
        sensor_mode = 'sim' if mode == "Симуляция" else 'real'
        
        if st.button("Запустить цифровой двойник", key="start_twin_btn"):
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
                st.success("Цифровой двойник успешно запущен!")
            except Exception as e:
                st.error(f"Ошибка запуска: {str(e)}")
        
        if st.button("Остановить цифровой двойник", 
                    disabled=not st.session_state.get('sensor_running', False),
                    key="stop_twin_btn"):
            self.sensor_manager.stop()
            if self.db_manager:
                self.db_manager.close()
            st.session_state.sensor_running = False
            st.success("Работа цифрового двойника остановлена")

    def setup_sensor_tab(self):
        st.header("Панель мониторинга")
        
        # Проверяем, запущен ли цифровой двойник
        if not st.session_state.get('sensor_running', False) or self.sensor_manager is None:
            st.warning("Цифровой двойник не запущен. Запустите его на вкладке 'Запуск двойника'.")
            return
        
        # Переключатель режима сенсоров
        current_mode = st.session_state.get('sensor_mode', 'sim')
        new_mode = st.radio("Режим сенсоров", 
                        ["Симуляция", "Реальное оборудование"],
                        index=0 if current_mode == 'sim' else 1,
                        key="sensor_toggle_radio")
        
        if (new_mode == "Симуляция" and current_mode != 'sim') or \
        (new_mode == "Реальное оборудование" and current_mode == 'sim'):
            try:
                self.sensor_manager.set_mode('sim' if new_mode == "Симуляция" else 'real')
                st.session_state.sensor_mode = 'sim' if new_mode == "Симуляция" else 'real'
                st.experimental_rerun()
            except Exception as e:
                st.error(f"Ошибка смены режима: {str(e)}")
                return
        
        # Получение данных
        try:
            data = self.sensor_manager.get_data()
            if data:
                # Сохраняем данные в базу
                if self.db_manager:
                    try:
                        self.db_manager.store_sensor_data(data)
                    except Exception as e:
                        st.error(f"Ошибка сохранения данных: {str(e)}")
                
                # Отображение данных в соответствии со структурой базы
                sensor_data = data["sensor_data"]
                
                # Создаем датафрейм для отображения
                display_data = []
                
                # Данные плавки стали (steel_melting_data)
                if "temperature" in sensor_data:
                    display_data.append({"Параметр": "Температура стали", "Значение": sensor_data["temperature"], "Единица": "°C"})
                if "vibration_level" in sensor_data:
                    display_data.append({"Параметр": "Уровень вибрации", "Значение": sensor_data["vibration_level"], "Единица": "м/с²"})
                if "casting_speed" in sensor_data:
                    display_data.append({"Параметр": "Скорость разливки", "Значение": sensor_data["casting_speed"], "Единица": "м/мин"})
                if "cooling_water_flow" in sensor_data:
                    display_data.append({"Параметр": "Расход охлаждающей воды", "Значение": sensor_data["cooling_water_flow"], "Единица": "л/мин"})
                
                # Состояние оборудования (equipment_status)
                if "equipment_status" in sensor_data:
                    display_data.append({"Параметр": "Статус оборудования", "Значение": sensor_data["equipment_status"], "Единица": ""})
                if "wear_level" in sensor_data:
                    display_data.append({"Параметр": "Уровень износа", "Значение": sensor_data["wear_level"], "Единица": "%"})
                
                # Качество продукции (production_quality)
                if "defect_count" in sensor_data:
                    display_data.append({"Параметр": "Количество дефектов", "Значение": sensor_data["defect_count"], "Единица": "шт"})
                if "quality_score" in sensor_data:
                    display_data.append({"Параметр": "Оценка качества", "Значение": sensor_data["quality_score"], "Единица": "/100"})
                
                sensor_df = pd.DataFrame(display_data)
                
                # Отображаем данные в виде таблицы
                st.subheader("Текущие показания сенсоров")
                st.dataframe(sensor_df)
                
                # Обновляем историю данных
                if "temperature" in sensor_data:
                    # Добавляем новую точку данных
                    st.session_state.temperature_history.append({
                        "timestamp": datetime.fromtimestamp(data["timestamp"]),
                        "value": sensor_data["temperature"]
                    })
                    # Сохраняем только последние 100 точек
                    if len(st.session_state.temperature_history) > 100:
                        st.session_state.temperature_history = st.session_state.temperature_history[-100:]
                
                if "vibration_level" in sensor_data:
                    # Добавляем новую точку данных
                    st.session_state.vibration_history.append({
                        "timestamp": datetime.fromtimestamp(data["timestamp"]),
                        "value": sensor_data["vibration_level"]
                    })
                    # Сохраняем только последние 100 точек
                    if len(st.session_state.vibration_history) > 100:
                        st.session_state.vibration_history = st.session_state.vibration_history[-100:]
                
                # Визуализация в реальном времени
                col1, col2 = st.columns(2)
                
                # График температуры стали
                with col1:
                    # Создаем DataFrame из истории температуры
                    if st.session_state.temperature_history:
                        temp_df = pd.DataFrame(st.session_state.temperature_history)
                    else:
                        # Создаем пустой датафрейм с нужной структурой
                        temp_df = pd.DataFrame(columns=["timestamp", "value"])
                    
                    fig_temp = px.line(
                        temp_df,
                        x="timestamp",
                        y="value",
                        title="Температура стали, °C",
                        labels={"value": "Температура", "timestamp": "Время"},
                        height=300
                    )
                    # Добавляем критический порог
                    fig_temp.add_hline(
                        y=1520, 
                        line_dash="dash", 
                        line_color="red",
                        annotation_text="Критический порог",
                        annotation_position="bottom right"
                    )
                    # Устанавливаем диапазон осей для пустого графика
                    if temp_df.empty:
                        fig_temp.update_yaxes(range=[1500, 1600])
                        fig_temp.update_xaxes(range=[datetime.now() - timedelta(minutes=10), datetime.now()])
                    st.plotly_chart(fig_temp, use_container_width=True)

                # График вибрации оборудования
                with col2:
                    # Создаем DataFrame из истории вибрации
                    if st.session_state.vibration_history:
                        vib_df = pd.DataFrame(st.session_state.vibration_history)
                    else:
                        # Создаем пустой датафрейм с нужной структурой
                        vib_df = pd.DataFrame(columns=["timestamp", "value"])
                    
                    fig_vib = px.line(
                        vib_df,
                        x="timestamp",
                        y="value",
                        title="Вибрация оборудования, м/с²",
                        labels={"value": "Вибрация", "timestamp": "Время"},
                        height=300
                    )
                    # Добавляем критический порог
                    fig_vib.add_hline(
                        y=4.2, 
                        line_dash="dash", 
                        line_color="red",
                        annotation_text="Критический порог",
                        annotation_position="bottom right"
                    )
                    # Устанавливаем диапазон осей для пустого графика
                    if vib_df.empty:
                        fig_vib.update_yaxes(range=[0, 10])
                        fig_vib.update_xaxes(range=[datetime.now() - timedelta(minutes=10), datetime.now()])
                    st.plotly_chart(fig_vib, use_container_width=True)
                
                # Проверка критических параметров из конфигурации двойника
                critical_alerts = []
                if "temperature" in sensor_data and sensor_data["temperature"] > 1520:
                    critical_alerts.append(f"Температура критическая: {sensor_data['temperature']:.1f}°C")
                
                if "vibration_level" in sensor_data and sensor_data["vibration_level"] > 4.2:
                    critical_alerts.append(f"Вибрация превышена: {sensor_data['vibration_level']:.2f} м/с²")
                
                if "cooling_water_flow" in sensor_data and sensor_data["cooling_water_flow"] < 1200:
                    critical_alerts.append(f"Расход воды низкий: {sensor_data['cooling_water_flow']:.0f} л/мин")
                
                if "casting_speed" in sensor_data and sensor_data["casting_speed"] < 1.8:
                    critical_alerts.append(f"Скорость разливки низкая: {sensor_data['casting_speed']:.2f} м/мин")
                
                if critical_alerts:
                    st.error("КРИТИЧЕСКИЕ ПРЕДУПРЕЖДЕНИЯ:")
                    for alert in critical_alerts:
                        st.markdown(f"⚠️ {alert}")
                
                # Показатели качества из production_quality
                st.subheader("Показатели качества продукции")
                quality_cols = st.columns(3)
                with quality_cols[0]:
                    defect_count = sensor_data.get("defect_count", 0)
                    st.metric("Дефекты на партию", f"{defect_count} шт", help="Количество дефектных изделий в текущей партии")
                
                with quality_cols[1]:
                    quality_score = sensor_data.get("quality_score", 0)
                    st.metric("Оценка качества", f"{quality_score:.1f}/100", help="Общая оценка качества продукции")
                
                with quality_cols[2]:
                    if "casting_speed" in sensor_data:
                        st.metric("Скорость производства", f"{sensor_data['casting_speed']:.2f} м/мин")
                
                # Состояние оборудования из equipment_status
                st.subheader("Состояние оборудования")
                equipment_cols = st.columns(2)
                with equipment_cols[0]:
                    if "wear_level" in sensor_data:
                        wear = sensor_data["wear_level"]
                        wear_status = "Норма" if wear < 70 else "Повышенный" if wear < 85 else "Критический"
                        st.metric("Уровень износа кристаллизатора", f"{wear:.1f}%", wear_status)
                
                with equipment_cols[1]:
                    if "equipment_status" in sensor_data:
                        status = sensor_data["equipment_status"]
                        status_color = "green" if status == "normal" else "orange" if status == "warning" else "red"
                        st.metric("Статус оборудования", status, delta=None, delta_color=status_color)
                
                # Исторические данные с учетом структуры базы
                time_range = st.selectbox("Анализ данных", 
                                        ["15 минут", "1 час", "Смена (8 часов)"],
                                        key="time_range_select")
                minutes = 15 if time_range == "15 минут" else 60 if time_range == "1 час" else 480
                self.display_historical_data(minutes)
        except Exception as e:
            st.error(f"Ошибка получения данных: {str(e)}")

    def display_historical_data(self, minutes):
        """Display historical data from all tables"""
        try:
            time_threshold = datetime.now() - timedelta(minutes=minutes)
            
            # Steel Melting Data
            melting_query = """SELECT 
                    timestamp,
                    temperature,
                    vibration_level AS vibration,
                    furnace_id
                FROM steel_melting_data 
                WHERE timestamp >= %s
                ORDER BY timestamp"""
            
            self.db_manager.cursor.execute(melting_query, (time_threshold,))
            melting_results = self.db_manager.cursor.fetchall()
            
            # Equipment Status
            equipment_query = """SELECT 
                    timestamp,
                    wear_level,
                    status
                FROM equipment_status 
                WHERE timestamp >= %s
                ORDER BY timestamp"""
            
            self.db_manager.cursor.execute(equipment_query, (time_threshold,))
            equipment_results = self.db_manager.cursor.fetchall()
            
            # Production Quality
            quality_query = """SELECT 
                    timestamp,
                    defect_count,
                    quality_score
                FROM production_quality 
                WHERE timestamp >= %s
                ORDER BY timestamp"""
            
            self.db_manager.cursor.execute(quality_query, (time_threshold,))
            quality_results = self.db_manager.cursor.fetchall()
            
            # Display data if available
            if melting_results or equipment_results or quality_results:
                st.subheader(f"Данные за {minutes} минут")
                
                # Steel Melting Data Visualization
                if melting_results:
                    melting_df = pd.DataFrame(
                        melting_results, 
                        columns=["Время", "Температура", "Вибрация", "Печь"]
                    )
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        fig_temp = px.line(
                            melting_df,
                            x="Время",
                            y="Температура",
                            title="Температура стали по времени",
                            color="Печь"
                        )
                        st.plotly_chart(fig_temp, use_container_width=True)
                    
                    with col2:
                        fig_vib = px.line(
                            melting_df,
                            x="Время",
                            y="Вибрация",
                            title="Вибрация оборудования",
                            color="Печь"
                        )
                        st.plotly_chart(fig_vib, use_container_width=True)
                
                # Equipment Status Visualization
                if equipment_results:
                    equipment_df = pd.DataFrame(
                        equipment_results, 
                        columns=["Время", "Износ", "Статус"]
                    )
                    
                    fig_wear = px.line(
                        equipment_df,
                        x="Время",
                        y="Износ",
                        title="Уровень износа оборудования",
                        color="Статус"
                    )
                    st.plotly_chart(fig_wear, use_container_width=True)
                
                # Production Quality Visualization
                if quality_results:
                    quality_df = pd.DataFrame(
                        quality_results, 
                        columns=["Время", "Дефекты", "Качество"]
                    )
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        fig_defects = px.bar(
                            quality_df,
                            x="Время",
                            y="Дефекты",
                            title="Количество дефектов по партиям"
                        )
                        st.plotly_chart(fig_defects, use_container_width=True)
                    
                    with col2:
                        fig_quality = px.line(
                            quality_df,
                            x="Время",
                            y="Качество",
                            title="Оценка качества продукции"
                        )
                        st.plotly_chart(fig_quality, use_container_width=True)
        except Exception as e:
            st.error(f"Ошибка получения исторических данных: {str(e)}")


def main():
    interface = DigitalTwinInterface()

if __name__ == "__main__":
    main()