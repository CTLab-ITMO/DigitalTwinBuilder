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

def init_logs_dir():
    """Initialize logs directory"""
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
    with open(os.path.join(LOGS_DIR, "score_requirements.csv"), 'w+') as f:
        f.write("test_num, format, simularity, comment\n")
    with open(os.path.join(LOGS_DIR, "score_db.csv"), 'w+') as f:
        f.write("test_num, format, simularity, comment\n")

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


def evaluate_results(client, requirements_json_expected, requirements_json_actual, db_json_expected, db_json_actual, bar):
    """Evaluate both JSON and SQL results"""
    json_score = evaluate_json(client, requirements_json_expected, requirements_json_actual)
    bar()
    bar.text = f"json evaluated, score: {json_score.split()[0]}"
    
    sql_score = evaluate_json(client, db_json_expected, db_json_actual)
    bar()
    bar.text = f"sql evaluated, score: {sql_score.split()[0]}"
    return json_score, sql_score


def write_results(score, result_path): 
    """Write results to output files"""
    with open(result_path, 'a') as f:
        f.write(f"{",".join(map(str, score))}\n")
    print(f"Results written to {result_path}")

def process_json_pair(client, requirements_json_expected, db_json_expected, requirements_json_actual, db_json_actual, bar_context):
    """Process a single JSON requirements file with a new session"""
    # Evaluate results
    json_score, sql_score = evaluate_results(client, requirements_json_expected, requirements_json_actual, db_json_expected, db_json_actual, bar_context)
    
    # Write results
    req_result_path = os.path.join(LOGS_DIR, "score_requirements.csv")
    db_result_path = os.path.join(LOGS_DIR, "score_db.csv")
    write_results(json_score.split()[0], req_result_path)
    write_results(sql_score.split()[0], db_result_path)
    
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

def main():
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
    parser.set_defaults(db_agent_test=False)
    parser.set_defaults(ui_agent_test=False)
    args = parser.parse_args()

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Initialize logs directory
    init_logs_dir()
    
    # Initialize API session
    init_session()
    
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    
    # Parse command line arguments
    if len(sys.argv) > 4:
        req_json = sys.argv[1]
        sql_json = sys.argv[2]
        req_schema_json = sys.argv[3]
        db_schema_json = sys.argv[4]
    else:
        # Default to test files
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
    
    
    # Ensure we have matching pairs
    num_pairs = min(len(requirements_jsons), len(db_jsons))
    print(f"Processing {num_pairs} JSON pairs...")
    
    success_count = 0
    bars_per_test = 3 if args.ui_agent_test else 0
    bars_per_test += 4 if args.db_agent_test else 0
    with alive_bar(num_pairs * bars_per_test) as bar:
        for i, (requirements_json_expected, db_json_expected) in enumerate(zip(requirements_jsons, db_jsons)):
            if db_json_expected == {} and args.db_agent_test:
                print(f"Generating pair {i+1} due to empty expected SQL JSON")
                db_json_expected = gen_sql_json_single(client, requirements_json_expected)
                if db_json_expected == {}:
                    print(f"Failed to generate SQL JSON for pair {i+1}, skipping")
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
                    print(f"Exceeded maximum retries for pair {i+1}, skipping to next pair")
                    if args.ui_agent_test:
                        write_results([i, 0, 0, "UI agent failed to produce valid JSON after 5 retries"], os.path.join(LOGS_DIR, "score_requirements.csv"))
                    if args.db_agent_test:
                        write_results([i, 0, 0, "DB agent failed to produce valid JSON after 5 retries"], os.path.join(LOGS_DIR, "score_db.csv"))
                    bar(bar_before_test - bar.current + bars_per_test)
                    break
                try:
                    # Create a new session for each test pair
                    session_id = create_new_session()
                    print(f"Created session: {session_id}")
    
                    # Run UI agent and get requirements
                    if args.ui_agent_test:
                        requirements_json_actual = run_ui_agent(client, session_id, requirements_json_expected, bar)
                        req_result_path = os.path.join(LOGS_DIR, "score_requirements.csv")
                        if requirements_json_actual is None:
                            print(f"Failed to process UI agent for {requirements_json_expected}, retry {retry}/5")
                            retry += 1
                            bar(bar_before_test - bar.current)
                            continue
                        json_score = json_evaluation_new(requirements_json_expected, requirements_json_actual, requirements_schema)
                        write_results([i] + list(json_score), req_result_path)
                        bar()
    
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
    
    # Summary
    print(f"\nCompleted: {success_count}/{num_pairs} pairs processed successfully")

if __name__ == '__main__':
    main()
