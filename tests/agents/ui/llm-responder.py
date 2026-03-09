# streamlit_app.py
import requests
import time
import json
import os
from openai import OpenAI
import pprint
import logging
import sys
from alive_progress import alive_bar
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../src'))
from digital_twin_builder.prompts.system import DB, UI
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

def init_logs_dir():
    """Initialize logs directory"""
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
    with open(os.path.join(LOGS_DIR, "scores.csv"), 'w+') as f:
        f.write("json_score,sql_score\n")

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
def submit_chat_to_agent(agent_id, conversation_id, params={}, poll_timeout=60):
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

def evaluate_json(client, expected, actual):
    prompt = "Необходимо оценить насколько построенный json соответствует ожидаемому, оценивать нужно только существенные различия, такие как различающиеся числовые значения, пропущенные данные и так далее. Оценку необходимо дать от 0 до 1, где 0 - json файлы содержат полностью разные данные, 1 - json файлы содержат одни и те же данные. \nОтвет вывести в формате: \n[число] \n[Обоснование]"
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Ожидаемый: ```json{expected}``` Построенный: ```json{actual}```"}
    ]
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        stream=False
    )
    return response.choices[0].message.content

def run_ui_agent(client, session_id, json_original, bar):
    """Run UI agent to collect requirements from JSON data"""
    conversations = []
    conversations.append(create_new_conversation(session_id, 1, UI))
    bar()
    bar.text = f"conversation {conversations[-1]} created"
    
    # Initialize conversation log
    log_file = get_log_filename(conversations[0], "ui")
    append_to_log(log_file, "SYSTEM", f"Conversation ID: {conversations[0]}")
    append_to_log(log_file, "SYSTEM", f"Session ID: {session_id}")

    system_msg = f"Ты должен отвечать на заданные вопросы, информацию нужно брать из следующего json: ```json\n{json_original}\n```\nНельзя придумывать новую информацию, если информации нет в json. \nНЕ используй markdown форматирование в ответе. Старайся давать краткие и понятные ответы."
    messages = [{"role": "system", "content": system_msg}]
    append_to_log(log_file, "SYSTEM", system_msg)
    
    retry = 0
    while True:
        try:
            if bar.current > 40 or retry > 5:
                return None, None
            task = submit_chat_to_agent(1, conversations[0])
            result = task.get("result", "")
            if result == "":
                task_id = task.get("task_id", "")
                print(f"no result on task {task_id}, retry {retry}/5")
                retry += 1
                continue
            else:
                retry = 0
            messages.append({"role": "user", "content": result})
            append_to_log(log_file, "AGENT", result)
            bar.text = f"agent: {result}"
            json_result = get_json(result)
            if json_result is None:
                print(f"agent did not return valid json, got: {result}")
                continue
            if json_result["completed"]:
                bar()
                bar.text = f"agent completed with json: {json_result}"
                return json_result["requirements"], conversations[0]
            
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
            print(f"Exception: {e}, retry {retry}/5")
            append_to_log(log_file, "ERROR", str(e))
            retry += 1
    return None, None


def run_db_agent(session_id, json_result, bar):
    """Run DB agent to generate SQL from JSON requirements"""
    conversation = create_new_conversation(session_id, 2, DB)
    bar()
    bar.text = f"DB conversation {conversation} created"
    
    # Initialize conversation log
    log_file = get_log_filename(conversation, "db")
    append_to_log(log_file, "SYSTEM", f"Conversation ID: {conversation}")
    append_to_log(log_file, "SYSTEM", f"Session ID: {session_id}")
    append_to_log(log_file, "USER", f"Requirements: {json_result}")
    
    add_message_to_conversation(conversation, "user", json_result)
    bar()
    bar.text = f"added requirements to DB conversation"

    task = submit_chat_to_agent(2, conversation, params={"max_tokens": 10000}, poll_timeout=120)
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


def evaluate_results(client, requirements_json_expected, requirements_json_actual, db_json_expected, db_json_actual, bar):
    """Evaluate both JSON and SQL results"""
    json_score = evaluate_json(client, requirements_json_expected, requirements_json_actual)
    bar()
    bar.text = f"json evaluated, score: {json_score.split()[0]}"
    
    sql_score = evaluate_json(client, db_json_expected, db_json_actual)
    bar()
    bar.text = f"sql evaluated, score: {sql_score.split()[0]}"
    return json_score, sql_score


def write_results(json_score, sql_score, result_path): 
    """Write results to output files"""
    with open(result_path, 'a') as f:
        f.write(f"{json_score.split()[0]},{sql_score.split()[0]}\n")
    print(f"Results written to {result_path}")

def process_json_pair(client, requirements_json_expected, db_json_expected, bar_context):
    """Process a single JSON requirements file with a new session"""
    # Create a new session for each test pair
    session_id = create_new_session()
    print(f"Created session: {session_id}")
    
    # Run UI agent and get requirements
    requirements_json_actual, _ = run_ui_agent(client, session_id, requirements_json_expected, bar_context)
    if requirements_json_actual is None:
        print(f"Failed to process {requirements_json_expected}")
        return None
    
    # Run DB agent and get actual JSON
    db_json_actual = run_db_agent(session_id, requirements_json_actual, bar_context)
    
    # Evaluate results
    json_score, sql_score = evaluate_results(client, requirements_json_expected, requirements_json_actual, db_json_expected, db_json_actual, bar_context)
    
    # Write results
    result_path = os.path.join(LOGS_DIR, "scores.csv")
    write_results(json_score, sql_score, result_path)
    
    return True


def parse_json_arrays(requirements_jsons_path, sql_jsons_path):
    """Parse comma-separated JSON file paths"""
    with open(requirements_jsons_path, 'r') as f:
        requirements = f.read().strip()
        json_objects = json.loads(requirements)
    with open(sql_jsons_path, 'r') as f:
        sqls = f.read().strip()
        sql_json_objects = json.loads(sqls)
    return json_objects, sql_json_objects


def main():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Initialize logs directory
    init_logs_dir()
    
    # Initialize API session
    init_session()
    
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    
    # Parse command line arguments
    if len(sys.argv) > 2:
        req_json = sys.argv[1]
        sql_json = sys.argv[2]
    else:
        # Default to test files
        req_json = 'tests/agents/ui/jsons/requirements.json'
        sql_json = 'tests/agents/ui/jsons/sql.json'
    
    requirements_jsons, db_jsons = parse_json_arrays(req_json, sql_json)
    
    # Ensure we have matching pairs
    num_pairs = min(len(requirements_jsons), len(db_jsons))
    print(f"Processing {num_pairs} JSON pairs...")
    
    results = []
    with alive_bar(num_pairs * 7) as bar:
        for i in range(num_pairs):
            requirements_json_expected = requirements_jsons[i]
            db_json_expected = db_jsons[i]
            print(f"\nProcessing pair {i+1}/{num_pairs}: {requirements_json_expected} & {db_json_expected}")
            
            try:
                success = process_json_pair(client, requirements_json_expected, db_json_expected, bar)
                results.append(success)
            except Exception as e:
                print(f"Error processing pair: {e}")
                results.append(False)
    
    # Summary
    success_count = sum(1 for r in results if r)
    print(f"\nCompleted: {success_count}/{num_pairs} pairs processed successfully")

if __name__ == '__main__':
    main()
