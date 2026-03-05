import json

def make_db_prompt(requirements, *args):
    prompt = f"""
Generate a PostgreSQL database schema in json form for an industrial digital twin based on the following requirements:

{json.dumps(requirements, ensure_ascii=False, indent=2)}

The schema should include tables for:
- Sensor data (temperature, pressure, vibration, level, etc.)
- Equipment status
- Production quality metrics
- Material composition
- Maintenance history (optional)
- Events/alerts (optional)

The response should be a valid JSON object with descriptions of tables, columns, data types, constraints, and relationships."""
    return prompt

def make_ui_prompt(conversation_context, user_message, *args):
    prompt = f"""История разговора:
{conversation_context}

Пользователь: {user_message}

Проанализируй ответ пользователя. Если информации достаточно для создания цифрового двойника, верни JSON:
{{
    "completed": true,
    "requirements": {{
        "production_type": "описание типа производства",
        "processes": ["список процессов"],
        "equipment": ["список оборудования"],
        "sensors": ["список датчиков и параметров"],
        "goals": "цели создания цифрового двойника",
        "data_sources": "описание источников данных",
        "update_frequency": "частота обновления данных",
        "critical_parameters": {{"параметр": "пороговое_значение"}},
        "additional_info": "любая дополнительная важная информация"
    }},
    "message": "твой ответ пользователю, резюмируй собранную информацию"
}}

Если информации НЕ достаточно, верни JSON:
{{
    "completed": false,
    "message": "твой ответ с вопросами для уточнения"
}}

ВАЖНО: Верни ТОЛЬКО валидный JSON без markdown форматирования, без блоков кода (```), без пояснений. Начни сразу с открывающей фигурной скобки {{."""
    return prompt

def make_ui_backup_prompt(chat_history):
    prompt = f"""На основе следующей истории разговора с пользователем,
извлеки и структурируй всю информацию о производстве для создания цифрового двойника.

История разговора:
{chat_history}

Верни JSON со следующей структурой:
{{
    "production_type": "тип производства",
    "processes": ["список процессов"],
    "equipment": ["список оборудования"],
    "sensors": ["список датчиков и параметров"],
    "goals": "цели создания цифрового двойника",
    "data_sources": "источники данных",
    "update_frequency": "частота обновления",
    "critical_parameters": {{"параметр": "значение"}},
    "additional_info": "дополнительная информация"
}}

Верни ТОЛЬКО валидный JSON."""
    return prompt

def make_gen_conf(requirements, db_schema, *args):
    prompt = f"""Create a comprehensive digital twin configuration for the industrial facility.

Requirements:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Database Schema:
{json.dumps(db_schema, ensure_ascii=False, indent=2)}

The configuration should include:
1. Components: Data collection modules, analytics engines, ML models, visualization dashboards
2. Data flows: Connections between components with protocols (OPC-UA, MQTT, REST, WebSocket) and update frequencies
3. Visualization: Dashboard layout, widget types, refresh rates, color schemes
4. Alerts: Threshold-based alerts with severity levels (info, warning, critical, emergency)
5. KPIs: Key performance indicators with target values and measurement methods

Return a well-structured JSON configuration that can be used to deploy the digital twin system.
Start directly with the opening brace {{."""
    return prompt

def make_gen_sim(requirements, db_schema, *args):
    prompt = f"""Generate a complete PyChrono simulation script for the digital twin.

Requirements:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Database Schema:
{json.dumps(db_schema, ensure_ascii=False, indent=2)}

The Python script should:
1. Import necessary PyChrono modules
2. Initialize the Chrono system
3. Create physical bodies representing equipment (furnaces, crystallizers, rollers, etc.)
4. Set up materials with appropriate properties (steel, refractory, etc.)
5. Define joints and constraints between bodies
6. Implement sensors to measure simulation parameters
7. Create a simulation loop that:
   - Steps the simulation forward in time
   - Collects sensor data
   - Logs data that matches the database schema tables
8. Include error handling and proper cleanup

The code should be production-ready and executable. Do not include markdown formatting or code blocks.
Start directly with import statements."""
    return prompt

def make_gen_db(db_schema, *args):
    prompt = f"""Generate complete PostgreSQL SQL code to create the database schema.

Database Schema:
{json.dumps(db_schema, ensure_ascii=False, indent=2)}

The SQL should include:
1. CREATE TABLE statements for all tables with proper column types and constraints
2. PRIMARY KEY and FOREIGN KEY constraints
3. CREATE INDEX statements for performance optimization
4. Comments describing each table and important columns
5. Any necessary sequences or triggers

The SQL should be production-ready and follow PostgreSQL best practices.
Do not include markdown formatting. Start directly with SQL statements."""
    return prompt

def make_mod_conf(old_config, modification_instructions, *args):
    prompt = f"""Here is the current digital twin configuration:
{json.dumps(old_config, ensure_ascii=False, indent=2)}

Please modify the configuration according to the following instructions:
{modification_instructions}

Return ONLY the updated configuration in valid JSON format without markdown formatting.
Start directly with the opening brace {{."""
    return prompt
