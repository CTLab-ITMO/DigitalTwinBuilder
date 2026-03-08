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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))
from digital_twin_builder.prompts.system import DB_old as DB, UI_old as UI
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

# Helper functions
def submit_chat_to_agent(agent_id, conversation_id, params={}):
    task_info = submit_task(agent_id, conversation_id, params)
    if task_info:
        task_id = task_info['task_id']
        return poll_task_result(task_id)
    return {}

def contains_json(message: str):
    try:
        start = message.find('{')
        end = message.rfind('}')
        json_result = message[start:end+1]
        json.loads(json_result)
        return True
    except ValueError:
        return False

def get_sql(client, json_data):
    messages = [{"role": "system", "content": DB},
                {"role": "user", "content": str(json_data)}]
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        stream=False
    )

    db_result = response.choices[0].message.content

    start = db_result.find("INSERT")
    end = db_result.rfind(";")
    sql_query = db_result[start:end + 1]
    return sql_query

def evaluate_json(client, expected, actual):
    messages = [{"role": "system", "content": "Необходимо оценить насколько построенный json соответствует ожидаемому, оценивать нужно только существенные различия, такие как различающиеся числовые значения, пропущенные данные и так далее. Оценку необходимо дать от 0 до 1, где 0 - json файлы содержат полностью разные данные, 1 - json файлы содержат одни и те же данные. \nОтвет вывести в формате: \n[число] \n[Обоснование]"},
                {"role": "user", "content": \
                 f"Ожидаемый: ```json{expected}``` \
                 Построенный: ```json{actual}```" \
                 }]
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        stream=False
    )

    score = response.choices[0].message.content
    return score


def evaluate_db(client, expected, actual):
    messages = [{"role": "system", "content": "Необходимо оценить насколько построенный sql запрос соответствует ожидаемому, оценивать нужно только существенные различия, такие как различающиеся числовые значения, пропущенные данные и так далее. Оценку необходимо дать от 0 до 1, где 0 - запросы создают совершенно разные данные или построенный запрос невалидный, 1 - запросы содержат одни и те же данные. \nОтвет вывести в формате: \n[число] \n[Обоснование]"},
                {"role": "user", "content": \
                 f"Ожидаемый: ```sql{expected}``` \
                 Построенный: ```sql{actual}```" \
                 }]

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        stream=False
    )

    score = response.choices[0].message.content
    return score


def main():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Initialize API session
    init_session()
    
    client = OpenAI(api_key='sk-c6e4a1d681db4b41b46ef062bdf07c59', base_url="https://api.deepseek.com")
    json_path = sys.argv[1] if len(sys.argv) > 1 else 'tests/agents/ui/jsons/1.json'

    with alive_bar(30) as bar:
        session_id = create_new_session()
        bar()
        bar.text = f"session {session_id} created"

        conversations = []
        conversations.append(create_new_conversation(session_id, 1, UI))
        bar()
        bar.text = f"conversation {conversations[-1]} created"

        json_result = None
        json_original = None
        with open(json_path) as json_file:
            json_original = json.load(json_file)
            messages = [{"role": "system", "content": \
                         f"Ты должен отвечать на заданные вопросы, информацию нужно брать из следующего json: \
                         ```json\
                            {json_original}\
                         ```\
                         Нельзя придумывать новую информацию, если информации нет в json. \nНЕ используй markdown форматирование в ответе. Старайся давать краткие и понятные ответы."}]
        
        retry = 0
        while True:
            try:
                if bar.current > 40 or retry > 5:
                    exit()
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
                bar()
                bar.text = f"agent: {result}"
                if contains_json(result):
                    json_result = result
                    break

                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=messages,
                    stream=False
                )

                message = response.choices[0].message.content
                messages.append({"role": "assistant", "content": message})
                bar()
                bar.text = f"user: {message}"
                add_message_to_conversation(conversations[0], "user", message)
                bar()
                bar.text = f"added {message} to conversation"
            except Exception as e:
                print(f"Exception: str(e), retry {retry}/5")
                retry += 1
    
        json_score = evaluate_json(client, json_original, json_result)
        bar()
        bar.text = f"json evaluated, score: {json_score.split()[0]}"

        conversations.append(create_new_conversation(session_id, 2, DB))
        bar()
        bar.text = f"conversation {conversations[-1]} created"
        add_message_to_conversation(conversations[1], "user", json_result)
        bar()
        bar.text = f"added {json_result} to conversation"

        task = submit_chat_to_agent(2, conversations[1])
        db_result = task.get("result", "")
        logger.debug({"role": "db_agent", "content": db_result})
        start = db_result.find("INSERT")
        end = db_result.rfind(";")
        sql_query = db_result[start:end + 1]
        bar()
        bar.text = f"got actual sql"
        
        sql_original = get_sql(client, json_original)
        bar()
        bar.text = f"got expected sql"
        sql_score = evaluate_db(client, sql_original, sql_query)
        bar()
        bar.text = f"sql evaluated, score: {sql_score.split()[0]}"
    
    file_without_ext = os.path.splitext(os.path.split(json_path)[-1])[0]
    
    dir_path = os.path.dirname(os.path.realpath(__file__))
    out_dir = os.path.join(dir_path, "out", file_without_ext)
    os.makedirs(out_dir, exist_ok = True)
    with open(os.path.join(out_dir, "conversation"), 'w+') as f:
        f.write(str(messages))
    print("conversations written")
    with open(os.path.join(out_dir, "score-responses"), 'w+') as f:
        f.write(f"Json score: \n{json_score}, \n\nSql score: \n{sql_score}")
    print("score responses written")
    with open(os.path.join(dir_path, "scores.csv"), 'a') as f:
        f.write(f"{file_without_ext},{json_score.split()[0]},{sql_score.split()[0]}\n")
    print("scores.csv written")

if __name__ == '__main__':
    main()
