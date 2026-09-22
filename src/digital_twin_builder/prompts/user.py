import json

def init_ui_assistant_answer(*args):
    return "Привет! Я помогу тебе создать цифровой двойник твоего производства. Пожалуйста, расскажи мне о своем производстве: какой это тип производства, какие процессы там происходят, какое оборудование используется, какие датчики установлены и какие цели ты хочешь достичь с помощью цифрового двойника?"

def make_ui_prompt(conversation_context, user_message, *args):
    prompt = f"""История разговора:s
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
        "line": {{
            "topology": "serial | serial_with_parallel | assembly | other",
            "source": {{"inter_arrival_time_s": null}},
            "stations": [
                {{
                    "id": "M1",
                    "processing_time_s": null,
                    "availability_pct": null,
                    "mttr_s": null,
                    "power_working_kw": null,
                    "power_idle_kw": null
                }}
            ],
            "buffers": [
                {{"id": "B0", "capacity": null, "before": "source", "after": "M1"}}
            ],
            "defects": {{"rate": null}}
        }},
        "des_horizon": {{"warmup_s": null, "window_s": null, "replications": null}},
        "units": {{"time": "s", "power": "kW", "energy": "kWh"}},
        "additional_info": "любая дополнительная важная информация"
    }},
    "message": "твой ответ пользователю, резюмируй собранную информацию"
}}

Если информации НЕ достаточно, верни JSON:
{{
    "completed": false,
    "message": "твой ответ с вопросами для уточнения"
}}

ПРАВИЛА ДЛЯ ЧИСЛОВЫХ ПОЛЕЙ (блок "line", "des_horizon"):
- Заполняй их ТОЛЬКО теми числами, которые пользователь назвал явно. Текстовые
  описания из "equipment" и "sensors" дублируй в "line" числами, если число в
  них названо ("среднее время обработки 149.9 с", "доступность 99.45 %").
- Если число не названо — ставь null. НЕ выдумывай, НЕ оценивай, НЕ подставляй
  "типичные" или "правдоподобные" значения и НЕ переноси число от одного
  станка к другому.
- Единицы: время в секундах, мощность в кВт. Если пользователь назвал время в
  минутах/часах — переведи в секунды. Если мощность не названа — null.
- "buffers": по одной записи на каждый буфер, "before"/"after" — id источника,
  станка или "sink". "capacity" — целое число, null если не названо.
- "topology": "serial" если станки соединены в одну цепочку.

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
    "line": {{
        "topology": "serial | serial_with_parallel | assembly | other",
        "source": {{"inter_arrival_time_s": null}},
        "stations": [
            {{
                "id": "M1",
                "processing_time_s": null,
                "availability_pct": null,
                "mttr_s": null,
                "power_working_kw": null,
                "power_idle_kw": null
            }}
        ],
        "buffers": [
            {{"id": "B0", "capacity": null, "before": "source", "after": "M1"}}
        ],
        "defects": {{"rate": null}}
    }},
    "des_horizon": {{"warmup_s": null, "window_s": null, "replications": null}},
    "units": {{"time": "s", "power": "kW", "energy": "kWh"}},
    "additional_info": "дополнительная информация"
}}

Числа в "line" и "des_horizon" бери только из разговора. Если число не названо,
ставь null — не выдумывай и не оценивай. Время в секундах, мощность в кВт.

Верни ТОЛЬКО валидный JSON."""
    return prompt

def make_gen_conf(requirements, db_schema, *args):
    prompt = f"""Create a comprehensive digital twin configuration for the industrial facility.

Requirements:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Database Schema:
{db_schema}

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
{db_schema}

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

def make_gen_des(requirements, db_schema, *args):
    prompt = f"""Adapt the reference SimPy program given in your system instructions to the production line below, and return the adapted program.

Requirements:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Database Schema:
{db_schema}

The reference program is already a correct DES of a serial line and already
computes the three KPIs as they are defined. Keep its model and its KPI block and
change only what the line requires: the values in the PARAMETERS block, and the
length of the STATIONS and BUFFERS lists if this line has a different number of
stations or buffers. Do not re-derive the KPIs and do not replace the code below
the PARAMETERS block with your own.

Build the model from requirements.line: the source, the stations, the buffers and
the topology. Use the numeric parameters exactly as given. Where a parameter is
null, omit the mechanism it drives instead of inventing a value.

Simulate for des_horizon.warmup_s + des_horizon.window_s seconds, discard
everything before des_horizon.warmup_s, and measure every KPI over
[des_horizon.warmup_s, des_horizon.warmup_s + des_horizon.window_s].
Run des_horizon.replications independent replications with a distinct fixed seed
each and report the mean of each KPI.

KPI definitions to use exactly:
- throughput: parts that left the last station during the measurement window,
  divided by (window_s / 3600) — parts/hour.
- WIP: time-average number of parts in the system during the measurement window
  (in buffers, in process and blocked) — parts.
- energy per part: total energy consumed during the measurement window in kWh,
  divided by parts produced in that window — kWh/part.

Print as the LAST THREE lines of stdout, exactly in this form:
    Throughput = <value> parts/hour
    WIP = <value> parts
    Mean Energy Consumption per Part = <value> kWh/part

Return only the Python code, without markdown formatting or code blocks. Start
directly with import statements."""
    return prompt

def make_gen_des_repair(requirements, db_schema, previous_code, failure_report,
                        attempt, total_attempts, *args):
    """Follow-up turn for the DES slot: the previous program was run and failed.

    `failure_report` is what executing the previous program actually produced —
    a Python traceback, a timeout notice, or the fact that no KPI contract line
    was printed. It is fed back verbatim so the model corrects the defect it can
    see rather than writing a fresh program from scratch.
    """
    prompt = f"""The Python program you returned did not run successfully.

Execution result of your previous program:
{failure_report}

Here is that program:
{previous_code}

Fix the defect the execution result shows and return the corrected program.
Keep the model of the line unchanged: the same source, stations, buffers,
topology and numeric parameters from requirements.line. Do not simplify the
model, do not drop a station or a buffer, and do not replace the KPI
computations with constants or with a formula that does not count the events.

When the execution result is an accuracy verdict rather than a traceback, you
have replaced the reference program's model or its KPI block with one of your own
and that replacement is what printed the implausible number. The remedy is to go
back to the reference program given in your system instructions and adapt it
again, changing only the PARAMETERS block (and the length of the STATIONS and
BUFFERS lists): its KPI block is known to be correct, and it is the one that must
produce the three printed lines.

Requirements:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Database Schema:
{db_schema}

SimPy correctness reminders (the defect is usually one of these):
- `yield` accepts a SimPy event only — never None, a bool, a plain value, or the
  result of a helper that returns one.
- `env.process(x)` takes a generator object, never a second Process and never a
  function reference.
- Parts go in `simpy.Store(env, capacity=n)` and move with
  `yield store.put(part)` / `part = yield store.get()`; `simpy.Container` holds
  a quantity and cannot hold a part.
- Every generator must contain at least one `yield`; every name must be defined
  before its first use; the environment is built and run once per replication.

Simulate for des_horizon.warmup_s + des_horizon.window_s seconds, measure every
KPI over [des_horizon.warmup_s, des_horizon.warmup_s + des_horizon.window_s],
and run des_horizon.replications independent replications with distinct fixed
seeds, reporting the mean of each KPI.

KPI definitions to use exactly:
- throughput: parts that left the last station during the measurement window,
  divided by (window_s / 3600) — parts/hour.
- WIP: time-average number of parts in the system during the measurement window
  (in buffers, in process and blocked) — parts.
- energy per part: total energy consumed during the measurement window in kWh,
  divided by parts produced in that window — kWh/part.

Print as the LAST THREE lines of stdout, exactly in this form:
    Throughput = <value> parts/hour
    WIP = <value> parts
    Mean Energy Consumption per Part = <value> kWh/part

Return only the Python code, without markdown formatting or code blocks. Start
directly with import statements. This is repair attempt {attempt} of
{total_attempts}."""
    return prompt

def make_db_prompt(dt_requirements, *args):
    prompt = f"""Generate complete PostgreSQL SQL to define the database schema for the digital twin based on the following requirements.

requirements json:
{json.dumps(dt_requirements, ensure_ascii=False, indent=2)}

Design rules:
1. Use a NARROW (long) shape for time-series data. Do NOT create one table per
   machine with a column per signal. Create dimension tables (machines, buffers,
   stations) keyed by id, and narrow fact tables, for example
   events(ts timestamptz, machine_id text, reason_code text, duration_s double
   precision, energy_kwh double precision) and
   samples(ts timestamptz, machine_id text, tag text, value double precision).
2. Sensors are addressed by tag/register identifier, which is not a machine name.
   Create tag_map(tag_id text primary key, machine_id text, signal text,
   unit text, register text, scale double precision) so an incoming register
   value can be resolved to a machine and a physical quantity. Populate tag_map
   only from identifiers named in the requirements; leave it empty (no INSERT)
   if the requirements name none.
3. Land raw payloads first: create
   raw_ingest(ingested_at timestamptz, source text, payload jsonb)
   and expose the typed fact tables as views over it, so an incorrect schema
   guess cannot reject arriving data.
4. Time: every fact table carries ts timestamptz. Document the unit of every
   duration/delay column in a COMMENT (the requirement units are seconds).
   Create ingest_watermark(source text primary key, max_event_ts timestamptz) so
   a consumer can query a reproducible as-of snapshot of the data.
5. Add an index on (machine_id, ts) for each fact table.

The SQL should include CREATE TABLE and CREATE VIEW statements with proper
column types and constraints. Include INSERT statements ONLY for dimension rows
that are explicitly enumerated in the requirements json. DO NOT add any other
data. DO NOT add demonstration, sample or placeholder data to any fact table.
The SQL should be production-ready and follow PostgreSQL best practices."""
    return prompt

def make_db_repair(dt_requirements, previous_sql, failure_report,
                   attempt, total_attempts, *args):
    """Follow-up turn for the DB slot: the previous reply was not a usable schema.

    `failure_report` is what validating the previous reply actually found — the
    parse defect, the missing or duplicated definition, or the relation that is
    used but never created. It is fed back verbatim so the model corrects the
    defect it can see rather than writing a fresh schema from scratch.
    """
    prompt = f"""The SQL you returned is not a usable PostgreSQL schema.

Validation result of your previous reply:
{failure_report}

Here is that reply:
{previous_sql}

Fix the defect the validation result shows and return the corrected SQL.
Keep the schema the same otherwise: the same tables, the same columns and the
same dimension rows. Do not drop a table to make the error go away, and do not
replace the schema with a JSON description of it — a JSON document is not SQL
and cannot be executed.

Every statement must be complete and separate: each `CREATE TABLE` closed with
its `)` and a `;`, every string literal closed on the same line it opens, and
every table a statement reads from or writes to created earlier in the same
reply. Create each table once, and give the tables, views and index targets
names that exist.

requirements json:
{json.dumps(dt_requirements, ensure_ascii=False, indent=2)}

The SQL must include CREATE TABLE statements, and CREATE VIEW statements where a
view is useful, with proper column types and constraints. Include INSERT
statements ONLY for dimension rows that are explicitly enumerated in the
requirements json. DO NOT add any other data, and DO NOT add demonstration,
sample or placeholder data to any fact table. Return only the SQL code, without
markdown formatting or code blocks. This is repair attempt {attempt} of
{total_attempts}."""
    return prompt

def make_mod_conf(old_config, modification_instructions, *args):
    prompt = f"""Here is the current digital twin configuration:
{json.dumps(old_config, ensure_ascii=False, indent=2)}

Please modify the configuration according to the following instructions:
{modification_instructions}

Return ONLY the updated configuration in valid JSON format without markdown formatting.
Start directly with the opening brace {{."""
    return prompt
