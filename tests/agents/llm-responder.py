# streamlit_app.py
import json
from operator import index
import os
from openai import OpenAI
import logging
import sys
from alive_progress import alive_bar, alive_it
from datetime import datetime
from deep_json_eval import compare_values, json_evaluation_new
from judge_llm_eval import evaluate_json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))
from digital_twin_builder.prompts.system import DB, UI
from digital_twin_builder.prompts.user import make_db_prompt
from digital_twin_builder.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, LLM_MODEL
from digital_twin_builder.api_utils import (
    init_session,
    submit_task,
    add_message_to_conversation,
    get_task_status,
    get_agent_status,
    poll_task_result,
    create_new_conversation,
    create_new_session
)

# Conversation logging setup
LOGS_DIR = "conversation_logs"
CSV_DELIMIT = ","

def init_logs_dir(args):
    """Initialize logs directory"""
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
    if args.ui_agent_test:
        headers = ["test_num"]
        if args.deep_eval:
            headers += ["format_score", "similarity_score", "comment"]
        if args.jllm_eval:
            headers += ["jllm_score", "jllm_comment"]
        with open(os.path.join(LOGS_DIR, "score_requirements.csv"), 'w+') as f:
            f.write(CSV_DELIMIT.join(headers) + "\n")
    if args.db_agent_test:
        with open(os.path.join(LOGS_DIR, "score_db.csv"), 'w+') as f:
            f.write("test_num" + CSV_DELIMIT + "format" + CSV_DELIMIT + "simularity" + CSV_DELIMIT + "comment\n")

def get_log_filename(conversation_id, agent_type):
    """Generate log filename from conversation ID and current timestamp"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    conv_id_short = str(conversation_id)[:8]
    return os.path.join(LOGS_DIR, f"{timestamp}_{agent_type}_{conv_id_short}.log")

def append_to_log(log_file, role, message):
    """Append a message to conversation log file"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {role}: {message}\n"
    with open(log_file, 'a') as f:
        f.write(log_entry)

# Helper functions
def submit_chat_to_agent(agent_id, conversation_id, params={}, poll_timeout=180):
    task_info = submit_task(agent_id, conversation_id, params)
    if task_info:
        task_id = task_info['task_id']
        return poll_task_result(task_id, max_poll=poll_timeout)
    return {}

def get_json(message: str):
    try:
        start = message.find('{')
        end = message.rfind('}')
        json_result = message[start:end+1]
        return json.loads(json_result)
    except ValueError:
        return None


def run_ui_agent(client, session_id, json_original, bar):
    ui_agent_id = 0
    """Run UI agent to collect requirements from JSON data"""
    conversations = []
    conversations.append(create_new_conversation(session_id, ui_agent_id, UI))
    bar()
    print(f"conversation {conversations[0]} created")
    
    # Initialize conversation log
    log_file = get_log_filename(conversations[0], "ui")
    append_to_log(log_file, "SYSTEM", f"Conversation ID: {conversations[0]}")
    append_to_log(log_file, "SYSTEM", f"Session ID: {session_id}")

    system_msg = f"Ты должен отвечать на заданные вопросы, информацию нужно брать из следующего json: ```json\n{json_original}\n```\nНельзя придумывать новую информацию, если информации нет в json. \nНЕ используй markdown форматирование в ответе. Старайся давать краткие и понятные ответы. Не повторяй вопросы пользователя, давай только ответы на них."
    messages = [{"role": "system", "content": system_msg}]
    append_to_log(log_file, "SYSTEM", system_msg)
    
    while True:
        try:
            task = submit_chat_to_agent(ui_agent_id, conversations[0])
            result = task.get("result", "")
            if result == "":
                task_id = task.get("task_id", "")
                print(f"no result on task {task_id}")
                return None
            json_result = get_json(result)
            if json_result is None:
                print(f"agent did not return valid json, got: {result}")
                return None

            messages.append({"role": "user", "content": json_result["message"]})
            append_to_log(log_file, "AGENT", result)
            bar.text = f"agent: {result}"
            if json_result["completed"]:
                bar()
                bar.text = f"agent completed with json: {json_result}"
                return {"requirements": json_result["requirements"]}
            
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                stream=False
            )
            message = response.choices[0].message.content
            messages.append({"role": "assistant", "content": message})
            append_to_log(log_file, "USER", message)
            bar.text = f"user: {message}"
            add_message_to_conversation(conversations[0], "user", message)
        except Exception as e:
            print(f"Exception: {e}")
            append_to_log(log_file, "ERROR", str(e))
            return None


def run_db_agent(session_id, json_result, bar):
    db_agent_id = 1
    """Run DB agent to generate SQL from JSON requirements"""
    conversation = create_new_conversation(session_id, db_agent_id, DB)
    bar()
    print(f"DB conversation {conversation} created")
    
    # Initialize conversation log
    log_file = get_log_filename(conversation, "db")
    append_to_log(log_file, "SYSTEM", f"Conversation ID: {conversation}")
    append_to_log(log_file, "SYSTEM", f"Session ID: {session_id}")
    append_to_log(log_file, "USER", f"Requirements: {json_result}")
    
    add_message_to_conversation(conversation, "user", make_db_prompt(json_result))
    bar()
    bar.text = f"added requirements to DB conversation"

    task = submit_chat_to_agent(db_agent_id, conversation, params={"max_tokens": 10000}, poll_timeout=180)
    print(str(task))
    db_result = task.get("result", "")
    append_to_log(log_file, "AGENT", db_result)
    db_result_json = get_json(db_result)
    
    if db_result_json is None:
        print(f"DB agent did not return valid JSON, got: {db_result}")
        return None
    bar()
    bar.text = f"got actual sql"
    return db_result_json

def init_deepseek_chat(json_original: str):
    system_msg = (
        "Ты должен отвечать на заданные вопросы, информацию нужно брать из следующего json:\n"
        f"```json\n{json_original}\n```\n"
        "Нельзя придумывать новую информацию, если информации нет в json.\n"
        "НЕ используй markdown форматирование в ответе.\n"
        "Старайся давать краткие и понятные ответы.\n"
        "Не повторяй вопросы пользователя, давай только ответы на них."
    )
    messages = [{"role": "system", "content": system_msg}]
    return messages


def deepseek_turn(client, messages, ui_message: str):
    messages.append({"role": "user", "content": ui_message})
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        stream=False
    )
    answer = response.choices[0].message.content
    messages.append({"role": "assistant", "content": answer})
    return answer


def run_interview_with_deepseek(client, scenario, max_steps: int = 20):
    # 1. JSON сценария для системного промпта дипсика
    req = scenario.get("requirements", scenario)
    json_original = json.dumps(scenario["requirements"], ensure_ascii=False, indent=2)
    messages_ds = init_deepseek_chat(json_original)

    # 2. Создать сессию и UI-конверсацию
    session_id = create_new_session()
    print(f"DT session created: {session_id}")

    ui_agent_id = 0  # UI_AGENT_INDEX
    conversation_id = create_new_conversation(session_id, ui_agent_id, UI)
    print(f"DT UI conversation {conversation_id} created")

    # 3. Стартовый запрос “пользователя” в нашу систему
    initial_user_message = (
        "Мне нужно настроить цифровой двойник под описанный процесс. "
        "Задавайте уточняющие вопросы."
    )
    add_message_to_conversation(conversation_id, "user", initial_user_message)

    log_file = get_log_filename(conversation_id, "dt_ui")
    append_to_log(log_file, "SYSTEM", f"DT Conversation ID: {conversation_id}")
    append_to_log(log_file, "SYSTEM", f"Session ID: {session_id}")
    append_to_log(log_file, "USER", initial_user_message)

    final_requirements = None
    final_message = None

    for step in range(max_steps):
        # 4. Ход UI-агента
        task = submit_chat_to_agent(
            ui_agent_id,
            conversation_id,
            params={"max_tokens": 1000},
            poll_timeout=180,
        )
        result = task.get("result", "")
        if result == "":
            task_id = task.get("task_id", "")
            print(f"no result on DT task {task_id}")
            break

        append_to_log(log_file, "AGENT", result)

        # 4.1. Пытаемся распарсить JSON
        json_result = get_json(result)

        if json_result is not None and isinstance(json_result, dict):
            # UI-агент вернул структурированный JSON
            completed = json_result.get("completed", False)
            ui_message = json_result.get("message", "")

            if "requirements" in json_result:
                final_requirements = json_result["requirements"]

            if ui_message:
                final_message = ui_message

            if completed:
                print(f"DT interview completed at step {step+1}")
                # интервью закончено, дипсика больше не спрашиваем
                break

            if not ui_message:
                print("DT UI agent returned JSON but without 'message'")
                break

            # интервью продолжится: JSON с completed=false и message
            ds_answer = deepseek_turn(client, messages_ds, ui_message)
            append_to_log(log_file, "DEEPSEEK", ds_answer)
            add_message_to_conversation(conversation_id, "user", ds_answer)

        else:
            # UI-агент вернул не-JSON (обычный текст)
            ui_message = result.strip()
            if not ui_message:
                print("DT UI agent returned empty text")
                break

            ds_answer = deepseek_turn(client, messages_ds, ui_message)
            append_to_log(log_file, "DEEPSEEK", ds_answer)
            add_message_to_conversation(conversation_id, "user", ds_answer)

    return {
        "session_id": session_id,
        "conversation_id": conversation_id,
        "requirements": final_requirements,
        "summary_message": final_message,
    }

def run_db_agent_for_requirements(requirements: dict, session_id: str) -> dict | str:
    """
    Создаёт отдельную DB-конверсацию, добавляет туда requirements и просит сгенерировать SQL/структуру.
    Возвращает либо распарсенный JSON, либо сырую строку.
    """
    db_agent_id = 1  # DB_AGENT_INDEX
    # создаём новый разговор специально для DB-агента
    conversation_id = create_new_conversation(session_id, db_agent_id, DB)
    print(f"DT DB conversation {conversation_id} created")

    log_file = get_log_filename(conversation_id, "dt_db")
    append_to_log(log_file, "SYSTEM", f"DT DB Conversation ID: {conversation_id}")
    append_to_log(log_file, "SYSTEM", f"Session ID: {session_id}")

    # Формируем юзер-промпт для DB-агента
    prompt = (
        "Вот JSON с требованиями к цифровому двойнику (production_type, processes, equipment, "
        "sensors, goals, data_sources, update_frequency, critical_parameters, additional_info).\n"
        "Сгенерируй JSON со структурой базы данных/SQL-конфигурацией для хранения измерений "
        "и конфигураций сенсоров под этот объект.\n"
        "Отвечай ТОЛЬКО валидным JSON без комментариев и пояснений."
    )
    requirements_str = json.dumps(requirements, ensure_ascii=False, indent=2)

    user_message = f"{prompt}\n\n```json\n{requirements_str}\n```"
    append_to_log(log_file, "USER", user_message)
    add_message_to_conversation(conversation_id, "user", user_message)

    # Запрашиваем ход DB-агента
    task = submit_chat_to_agent(
        db_agent_id,
        conversation_id,
        params={"max_tokens": 5000},
        poll_timeout=900,
    )
    result = task.get("result", "")
    append_to_log(log_file, "AGENT", result)

    if not result:
        print(f"DB agent returned empty result for conv {conversation_id}")
        return ""

    db_json = get_json(result)
    if db_json is None:
        print(f"DB agent did not return valid JSON, got: {result}")
        return result  # сырая строка, если JSON не распарсился

    return db_json

def run_coder_agent(session_id: str, base_conversation_id: str, requirements: dict, db_result: dict | str) -> str:
    """
    Запускает Qwen-coder агента в отдельной конверсации.
    В контекст кладём requirements и результат DB-агента.
    Возвращаем его текстовый ответ (код/конфиг).
    """
    dt_agent_id = 2  # DT_AGENT_INDEX
    conversation_id = create_new_conversation(session_id, dt_agent_id, DB)  # или отдельный SYSTEM промпт для кода
    print(f"DT Code conversation {conversation_id} created")

    log_file = get_log_filename(conversation_id, "dt_code")
    append_to_log(log_file, "SYSTEM", f"DT Code Conversation ID: {conversation_id}")
    append_to_log(log_file, "SYSTEM", f"Session ID: {session_id}")

    # Формируем системное сообщение для Qwen (можно вынести в промпты)
    system_msg = (
        "Ты — инженер, который пишет код на Python с использованием библиотеки PyChrono для цифрового двойника"
        "на основе требований и структуры базы данных.\n"
        "Сначала внимательно проанализируй входные JSON, затем сгенерируй законченный и исполняемый код на PyChrono.\n"
        "Не добавляй объяснений, только код на PyChrono."
    )
    sys_message = {"role": "system", "content": system_msg}
    add_message_to_conversation(conversation_id, "assistant", system_msg)  # чтобы попало в контекст

    requirements_str = json.dumps(requirements, ensure_ascii=False, indent=2)
    db_str = db_result if isinstance(db_result, str) else json.dumps(db_result, ensure_ascii=False, indent=2)

    user_message = (
        "Вот JSON с требованиями к цифровому двойнику:\n"
        f"```json\n{requirements_str}\n```\n\n"
        "Вот JSON/текст с проектируемой структурой базы данных:\n"
        f"```json\n{db_str}\n```"
    )
    append_to_log(log_file, "USER", user_message)
    add_message_to_conversation(conversation_id, "user", user_message)

    # Запускаем задачу на DT-агент
    task = submit_chat_to_agent(
        dt_agent_id,
        conversation_id,
        params={"max_tokens": 10000},
        poll_timeout=900,
    )
    result = task.get("result", "")
    append_to_log(log_file, "AGENT", result)

    return result




def write_results(score, result_path): 
    """Write results to output files"""
    with open(result_path, 'a') as f:
        f.write(f"{CSV_DELIMIT.join(map(str, score))}\n")
    print(f"Results written to {result_path}")

def parse_json_arrays(requirements_jsons_path, sql_jsons_path):
    """Parse comma-separated JSON file paths"""
    with open(requirements_jsons_path, 'r') as f:
        requirements = f.read().strip()
        json_objects = json.loads(requirements)
    with open(sql_jsons_path, 'r') as f:
        sqls = f.read().strip()
        sql_json_objects = json.loads(sqls)
    return json_objects, sql_json_objects


def gen_sql_json(client, requirements_jsons_path='tests/agents/jsons/requirements.json', sql_jsons_path='tests/agents/jsons/sql.json'):
    """Generate SQL JSON file from requirements JSON files"""
    print(f"Generating SQL JSON file at {sql_jsons_path}...")

    with open(requirements_jsons_path, 'r') as f:
        requirements = f.read().strip()
        json_objects = json.loads(requirements)
    
    sql_json_objects = []
    for req in alive_it(json_objects):
        sql_json = gen_sql_json_single(client, req)
        sql_json_objects.append(sql_json)
        with open(sql_jsons_path, 'w') as f:
            json.dump(sql_json_objects, f, ensure_ascii=False, indent=2)
        

def gen_sql_json_single(client, requirements_json):
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": DB},
            {"role": "user", "content": make_db_prompt(requirements_json)}
        ],
        stream=False
    )
    response_message = response.choices[0].message.content
    response_json = get_json(response_message)
    if response_json is None:
        print(f"Failed to generate SQL for requirements: {requirements_json}")
        response_json = {}
    return response_json

def gen_missing_sql_json(client, requirements_json_expected):
    print(f"Generating pair {i+1} due to empty expected SQL JSON")
    db_json_expected = gen_sql_json_single(client, requirements_json_expected)
    if db_json_expected == {}:
        print(f"Failed to generate SQL JSON for pair {i+1}, skipping")
        return None
    return db_json_expected

def retries_exceeded(args, i):
    print(f"Exceeded maximum retries for pair {i+1}, skipping to next pair")
    if args.ui_agent_test:
        values = [i]
        if args.deep_eval:
            values += ["0", "0", "UI agent failed to produce valid JSON after 5 retries"]
        if args.jllm_eval:
            values += ["0", "UI agent failed to produce valid JSON after 5 retries"]
        
        write_results(values, os.path.join(LOGS_DIR, "score_requirements.csv"))
    if args.db_agent_test:
        write_results([i, 0, 0, "DB agent failed to produce valid JSON after 5 retries"], os.path.join(LOGS_DIR, "score_db.csv"))

def parse_args():
    import argparse

    parser = argparse.ArgumentParser(description="Simple LLM Agent")
    parser.add_argument("--db_agent_test", action=argparse.BooleanOptionalAction,
                        help="Runs db agent for testing")
    parser.add_argument("--ui_agent_test", action=argparse.BooleanOptionalAction,
                        help="Runs ui agent for testion")
    parser.add_argument("--jllm_eval", action=argparse.BooleanOptionalAction,
                        help="Runs judge llm evaluation for testing")
    parser.add_argument("--deep_eval", action=argparse.BooleanOptionalAction,
                        help="Runs deep evaluation for testing")
    parser.add_argument("--deepseek_dt", action=argparse.BooleanOptionalAction,
                        help="Runs DeepSeek-as-user Digital Twin interviews from 30.json")
    parser.add_argument("--deepseek_dt_single", action=argparse.BooleanOptionalAction,
                    help="Runs full DT pipeline (UI+DeepSeek+DB+Coder) for one scenario from 30.json")

    parser.set_defaults(
        db_agent_test=False,
        ui_agent_test=False,
        jllm_eval=False,
        deep_eval=False,
        deepseek_dt=False,
        deepseek_dt_single=False
    )
    return parser.parse_args()

def main():
    args = parse_args()
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Initialize logs directory
    init_logs_dir(args)
    
    # Initialize API session
    init_session()
    
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    

    if args.deepseek_dt_single:
        # читаем только первый сценарий из 30.json
        with open("tests/agents/jsons/requirements.json", "r", encoding="utf-8") as f:
            scenarios = json.load(f)
        scenario = scenarios[0]  # берём первый элемент списка

        print("\n=== DT interview for single scenario ===")
        info = run_interview_with_deepseek(client, scenario)
        reqs = info["requirements"]

        if reqs is None:
            print("UI agent did not produce requirements, stopping.")
            return

        print("\n=== DB Agent on requirements ===")
        db_result = run_db_agent_for_requirements(reqs, info["session_id"])

        print("\n=== Qwen Coder Agent on requirements + DB result ===")
        code_result = run_coder_agent(info["session_id"], info["conversation_id"], reqs, db_result)

        # Можно сохранить все три артефакта в файл
        out = {
            "requirements": reqs,
            "db_result": db_result,
            "code_result": code_result,
        }
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(os.path.join(LOGS_DIR, "dt_single_result.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

        print("\nFull DT pipeline for single scenario completed. Results saved to dt_single_result.json.")
        return

    
    # --- Новый режим: DeepSeek как пользователь для 30 сценариев ---
    if args.deepseek_dt:
        with open("tests/agents/jsons/requirements.json", "r", encoding="utf-8") as f:
            scenarios = json.load(f)

        all_conversations = []
        for i, scenario in enumerate(scenarios):
            print(f"\n=== Running DeepSeek DT interview for scenario {i+1}/{len(scenarios)} ===")
            info = run_interview_with_deepseek(client, scenario)
            all_conversations.append({"index": i, **info})

        # карта сценарий -> session_id / conversation_id
        with open(os.path.join(LOGS_DIR, "dt_conversations_map.json"), "w", encoding="utf-8") as f:
            json.dump(all_conversations, f, ensure_ascii=False, indent=2)

        print("\nDeepSeek DT interviews completed.")
        return
    # --- конец нового режима ---


    req_json = 'tests/agents/jsons/requirements.json'
    sql_json = 'tests/agents/jsons/sql.json'
    req_schema_json = 'tests/agents/jsons/requirements_schema.json'
    db_schema_json = 'tests/agents/jsons/db_schema.json'

    if not os.path.exists(sql_json):
        gen_sql_json(client, req_json, sql_json)

    with open(req_schema_json, 'r') as f:
        requirements_schema = json.load(f)
    with open(db_schema_json, 'r') as f:
        db_schema = json.load(f)

    requirements_jsons, db_jsons = parse_json_arrays(req_json, sql_json)
    requirements_jsons_actual = []
    # with open(os.path.join(LOGS_DIR, "requirements_logs.json"), 'r') as f:
    #     requirements_jsons_actual = json.load(f) 
    
    # Ensure we have matching pairs
    num_pairs = min(len(requirements_jsons), len(db_jsons))
    print(f"Processing {num_pairs} JSON pairs...")
    
    success_count = 0
    bars_per_test = ((0 + args.jllm_eval + args.deep_eval) if args.ui_agent_test else 0) +\
                    (4 if args.db_agent_test else 0)
    
    with alive_bar(num_pairs * bars_per_test) as bar:
        for i, (requirements_json_expected, db_json_expected) in enumerate(zip(requirements_jsons, db_jsons)):
            if db_json_expected == {} and args.db_agent_test:
                db_json_expected = gen_missing_sql_json(client, requirements_json_expected)
                if db_json_expected is None:
                    bar(bars_per_test)
                    continue
                db_jsons[i] = db_json_expected
                with open(sql_json, 'w') as f:
                    json.dump(db_jsons, f, ensure_ascii=False, indent=2)

            print(f"\nProcessing pair {i+1}/{num_pairs}")
            retry = 0
            while True:
                bar_before_test = bar.current
                if retry > 5:
                    retries_exceeded(args, i)
                    bar(bars_per_test)
                    break
                try:
                    # Create a new session for each test pair
                    session_id = create_new_session()
                    print(f"Created session: {session_id}")
    
                    # Run UI agent and get requirements
                    if args.ui_agent_test: 
                        # requirements_json_actual = requirements_jsons_actual[i]
                        requirements_json_actual = run_ui_agent(client, session_id, requirements_json_expected, bar)
                        req_result_path = os.path.join(LOGS_DIR, "score_requirements.csv")
                        if requirements_json_actual is None:
                            print(f"Failed to process UI agent for {requirements_json_expected}, retry {retry}/5")
                            retry += 1
                            bar(bar_before_test - bar.current)
                            continue
                        json_score = []
                        if args.deep_eval:
                            json_score += json_evaluation_new(requirements_json_expected, requirements_json_actual, requirements_schema)
                            bar()
                        if args.jllm_eval:
                            result = evaluate_json(client, requirements_json_expected, requirements_json_actual)
                            score, comment = result.split(maxsplit=1)
                            comment = comment.replace(",", ";")
                            comment = comment.replace("\n", " ")
                            json_score += [score, comment]
                            bar()
                        requirements_jsons_actual.append(requirements_json_actual)
                        write_results([i] + list(json_score), req_result_path)
    
                    # Run DB agent and get actual JSON
                    if args.db_agent_test:
                        db_json_actual = run_db_agent(session_id, requirements_json_expected, bar)
                        db_result_path = os.path.join(LOGS_DIR, "score_db.csv")
                        if db_json_actual is None:
                            print(f"Failed to process db agent for {requirements_json_expected}, retry {retry}/5")
                            retry += 1
                            bar(bar_before_test - bar.current)
                            continue
                        sql_score = json_evaluation_new(db_json_expected, db_json_actual, db_schema)
                        write_results([i] + list(sql_score), db_result_path)
                        bar()
                    success_count += 1
                    break
                except Exception as e:
                    print(f"Error processing pair: {e}")
                    retry += 1
                    bar(bar_before_test - bar.current)
                    pass
    
    with open(os.path.join(LOGS_DIR, "requirements_logs.json"), 'w') as f:
        json.dump(requirements_jsons_actual, f, ensure_ascii=False, indent=2)
    # Summary
    print(f"\nCompleted: {success_count}/{num_pairs} pairs processed successfully")

if __name__ == '__main__':
    main()

