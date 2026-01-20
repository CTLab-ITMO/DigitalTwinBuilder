# streamlit_app.py
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import json
import os
from openai import OpenAI
import pprint
import logging
import sys
from alive_progress import alive_bar


DB = """
You are a Database Agent. Your task is to insert sensor device data from JSON into a PostgreSQL database.

Database schema:
1. devices table: id, device_name (unique), data_update_frequency, created_at
2. sensors table: id, device_id (foreign key), sensor_name, parameter_type, unit, measurement_range_min, measurement_range_max, alarm_threshold_min, alarm_threshold_max, created_at

Input: You will receive JSON data from the previous agent with device and sensor information.

Your steps:
1. Parse the JSON input
2. Insert into devices table: device_name and data_update_frequency
3. Get the device_id from the inserted device
4. For each sensor in the "sensors" array, insert into sensors table:
   - device_id (from step 3)
   - sensor_name
   - parameter_type
   - unit
   - measurement_range_min
   - measurement_range_max 
   - alarm_threshold_min
   - alarm_threshold_max
5. created_at fields will auto-populate with current timestamp

Output: return sql statements, that will insert necessary data

Now process the JSON data and insert into database.
"""
UI = """Ты — специалист по сбору данных для создания цифровых двойников промышленных приборов. Твоя задача — системно и последовательно собрать всю необходимую информацию у пользователя, строго следуя заданному списку вопросов.

Твои строгие правила работы:
1. Задавай только ОДИН вопрос за одно сообщение
2. Жди ответа пользователя на каждый вопрос перед тем, как задать следующий
3. Только после получения полного ответа на каждый вопрос, подтверди понимание и переходи к следующему
4. После сбора ВСЕХ данных, предоставь финальный JSON в указанном форматe

Список вопросов, которые ты должен задать строго по порядку:

1. Вопрос 1: Какое точное название прибора?

2. Вопрос 2: Сколько всего датчиков подключено к прибору?

3. Вопрос 3: Перечисли точные названия ВСЕХ датчиков через запятую.

4. Вопрос 4: Для каждого датчика из списка укажи:
   - Тип измеряемого параметра (температура, давление, вибрация, ток, напряжение и т.д.)
   - Единицы измерения (°C, Па, м/с², А, В и т.д.)
   - Диапазон измерений (минимальное и максимальное значение)
   Формат: [Название датчика]: [Тип], [Единицы измерения], [мин]-[макс]

5. Вопрос 5: Для каждого датчика из списка укажи: какова частота обновления данных с приборов? (Пример: "1 раз в секунду", "100 мс", "1 раз в минуту")

6. Вопрос 6: Укажи для каждого датчика критическое минимальное и максимальное значение.
   Формат: [Название датчика]: [критический минимум] - [критический максимум]

7. Вопрос 7: Для каждого датчика из списка укажи: Какие математические модели или алгоритмы обработки данных нужны? 
   (Калибровка, фильтрация, прогнозирование и т.д.)

После получения ответа на ВСЕ 8 вопросов, предоставь данные в следующем JSON-формате для передачи агенту создания базы данных:

{
  "device_name": "[Название прибора из вопроса 1]",
  "sensor_count": [Число из вопроса 2],
  "sensors": [
    {
      "sensor_name": "[Точное название датчика 1]",
      "parameter_type": "[Тип из вопроса 4]",
      "unit": "[Единицы измерения из вопроса 4]",
      "measurement_range": {
        "min": [Число из вопроса 4],
        "max": [Число из вопроса 4]
      },
      "alarm_thresholds": {
        "critical_min": [Число из вопроса 6],
        "critical_max": [Число из вопроса 6]
      }
      "data_update_frequency": "[Частота из вопроса 5]", // В герцах
      "data_processing_algorithms": [
        "[Алгоритм 1 из вопроса 7]",
        "[Алгоритм 2 из вопроса 7]",
        ...
      ]
    },
  ], // для каждого датчика
}

ВАЖНО: 
- Не обрабатывай ответы пользователя, пока не получишь ВСЕ ответы
- Не начинай создавать JSON до получения ответа на 7-й вопрос
- Не изменяй структуру JSON — используй точно такой формат
- Если пользователь отвечает неполно или неясно, уточни информацию по текущему вопросу, но НЕ переходи к следующему вопросу, пока не получишь полный ответ на текущий
- НИКОГДА не пиши ответы за пользователя, если информации не хватает для составления json запроси ее у пользователя и жди ответа

Начинай задавать вопросы:"""

# Configuration
API_URL = "http://188.119.67.226:8000"  # Change to your API URL
requests_session = None

# Helper functions
def submit_task(agent_id, conversation_id, params):
    """Submit task to API"""
    try:
        response = requests_session.post(
            f"{API_URL}/tasks",
            json={
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "params": params,
                "priority": 5
            },
            timeout=10
        )
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"API Error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
        return None

def add_message_to_conversation(conversation_id, role, content):
    try:
        response = requests_session.post(
            f"{API_URL}/conversations/{conversation_id}/messages", 
            params={
                "conversation_id": conversation_id,
                "role": role,
                "content": content},
            timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"API Error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
    return None

def get_task_status(task_id):
    """Get task status from API"""
    try:
        response = requests_session.get(f"{API_URL}/tasks/{task_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
    return None

def get_agent_status(agent_id):
    """Get agent status from API"""
    try:
        response = requests_session.get(f"{API_URL}/agents/{agent_id}/status", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
    return {"status": "offline"}

def poll_task_result(task_id):
    poll = 0
    max_poll = 30
    while (poll < max_poll):
        task = get_task_status(task_id)
        if task and task["status"] == "completed":
            return task
        else: 
            time.sleep(1)
        poll += 1
    return {"task_id": task_id}

def create_new_conversation(session_id, agent_id, system_prompt, metadata = {}):
    """Create a new conversation"""
    try:
        response = requests_session.post(
            f"{API_URL}/conversations",
            params={"session_id": session_id, "agent_id": agent_id}
        )
        if response.status_code == 200:
            conversation_id = response.json()["conversation_id"]
        else:
            logger.error(f"Не удалось создать новую беседу с агентом {agent_id}, запрос завершился с ошибкой {response.status_code}")
            return None
        response_message = add_message_to_conversation(conversation_id, "system", system_prompt)
        if response_message is not None:
            return conversation_id
        else:
            logger.error(f"Не удалось добавить системный промпт в новую беседу {conversation_id} с агентом {agent_id}")
            return None
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
    return None

def create_new_session():
    try:
        response = requests_session.post(
            f"{API_URL}/sessions",
            params={"user_id": "streamlit_user", "title": "New Chat"}
        )
        if response.status_code == 200:
            session_id = response.json()["session_id"]
            return session_id
        else:
            logger.error(f"Не удалось создать новую сессию, запрос завершился с ошибкой {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
    return None

def submit_chat_to_agent(agent_id, conversation_id, params = {}):
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

    global requests_session
    requests_session = requests.Session()
    retry = Retry(connect=3, backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    requests_session.mount('http://', adapter)
    requests_session.mount('https://', adapter)
    
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
