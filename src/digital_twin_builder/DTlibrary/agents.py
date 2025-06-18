import json
import logging
from llm import _model_call

class Agent(object):
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(self.name)

    def run(self, *args, **kwargs):
        # Метод для запуска работы агента.
        raise NotImplementedError


class UserInteractionAgent(Agent):
    def __init__(self, name="UserInteractionAgent"):
        super().__init__(name)
        self.prompt_template = """Задача: Ты - агент-интервьюер для сбора данных о предприятии (сотрудник - твой источник) для построения цифрового двойника производства. Проведи структурированное интервью, получая конкретные и детальные ответы.

Контекст: Сотрудник обладает знаниями о производственных процессах, оборудовании и инфраструктуре.

Инструкции:

1. Представься, объясни цель (цифровой двойник), заверь в конфиденциальности.
2. Общая информация:
    * Деятельность предприятия (что производит/услуги)?
    * Организационная структура (отделы, взаимодействие)?
    * Площадь производства (приблизительно)?
3. Цифровой двойник:
    * Какой процесс/участок оцифровать в первую очередь? Почему?
    * Подробное описание процесса/участка (шаг за шагом).
    * KPI для мониторинга процесса?
    * Проблемы процесса/участка?
4. Оборудование и инфраструктура:
    * Основное оборудование (название, модель, производитель, год)?
    * Связь оборудования (материалы, энергия, информация)?
    * Используемые системы автоматизации (SCADA, PLC, MES)?
    * Схемы расположения оборудования (если есть)?
5. Видеонаблюдение:
    * Система видеонаблюдения (охват процесса)?
    * Количество камер, расположение?
    * Характеристики камер (разрешение, FPS, угол)?
    * Сохранение видеопотока (где, срок)?
    * Видеоаналитика (какая)?
6. Датчики:
    * Используемые датчики (тип, параметр, расположение)?
    * Измеряемые параметры (температура, давление и т.д.)?
    * Частота сбора данных?
    * Передача данных (куда)?
    * Спецификации датчиков (если есть)?
7. База данных:
    * Данные для хранения (датчики, видео, оборудование, логи)?
    * Частота обновления данных?
    * Требования к масштабируемости?
8. Дополнительно:
    * Важные данные (документация, чертежи, анализы)?
    * Ограничения/требования (безопасность, конфиденциальность)?
    * Контакты для консультаций?
9. Завершение:
    * Благодарность за участие.
    * Информация об использовании данных.

Стиль: Вежливо, внимательно, уточняющие вопросы, избегай тех. терминов (если сотрудник не владеет).

Представь результаты интервью в виде JSON-объекта со следующей структурой:

json
{
  "introduction": "Твое представление и объяснение цели интервью сотруднику.",
  "general_information": {
    "enterprise_activity": "Деятельность предприятия (производство/услуги).",
    "organizational_structure": "Организационная структура (отделы, взаимодействие).",
    "production_area": "Площадь производства (приблизительно)."
  },
  "digital_twin": {
    "priority_process": {
      "process_name": "Процесс/участок, который следует оцифровать в первую очередь.",
      "reason": "Обоснование выбора процесса/участка."
    },
    "process_description": "Подробное описание процесса/участка (шаг за шагом).",
    "problems": "Проблемы процесса/участка."
  },
  "conclusion": "Твои заключительные слова благодарности сотруднику."
}
Теперь, начни интервью с сотрудником.
"""

    def generate_output(self, employee_id, model):
        self.prompt = self.prompt_template.replace("{{employee_name}}", employee_id)
        print("*")
        print("User Interaction Agent Working")
        print("*")
        print("Prompt:\n", self.prompt)

        try:
            text_output = _model_call(self.prompt, model=model)
        except Exception as e:
            print(f"Error: {e}")
            return None

        try:
            result_json = json.loads(text_output)
        except json.JSONDecodeError as json_err:
            print(f"JSON Decode Error: {json_err}")
            return None

        with open('user_interaction_agent.json', 'w') as file:
            json.dump(result_json, file, indent=4)
        print("Result:\n")
        print(text_output)
        return result_json
    
class DatabaseConfigurationAgent(Agent):
    def __init__(self, name="DatabaseConfigurationAgent"):
        super().__init__(name)
        self.prompt_template = """Task: You are a database design expert. Develop a database schema for a given application, considering its digital twin aspects.

Requirements:
You will receive a description of the application and its data storage requirements, focusing on the needs of its digital twin representation.
Design the database schema, including tables/collections, columns/fields, data types, and relationships.
Provide code (SQL, JSON Schema, etc.) to create the database structure.
Provide queries to perform basic operations (CRUD - Create, Read, Update, Delete) relevant to the digital twin.
Consider scalability, performance, and security factors crucial for the digital twin's responsiveness and reliability.  Include aspects of data synchronization and real-time updates if applicable.

Input:
Application description and data storage requirements (focusing on digital twin): {{application_description}}
Preferred database type (if any): {{preferred_database_type}}

Instructions:
1.  Analyze the application description and identify key entities and their attributes required for the digital twin.
2.  Select an appropriate database type based on these requirements (if no preferred type is specified).
3.  Design the database schema, considering the selected type.  Incorporate elements that facilitate the digital twin's real-time data reflection.
4.  Generate code to create the database structure.
5.  Provide example queries for basic operations critical for the digital twin's functionality.
6.  Justify your database type selection and schema design decisions, especially regarding the digital twin's needs.

Output Format:

Present the results as a JSON object with the following structure:
json
{
  "application_description": "Description of the application for which the database is created.",
  "database_type": "The selected database type (e.g., PostgreSQL, MongoDB).",
  "justification": "Justification for the database type selection, considering the digital twin.",
  "schema_description": "Description of the designed database schema, including digital twin-specific considerations.",
  "creation_code": "Code to create the database structure (SQL, JSON Schema, etc.).",
  "example_queries": {
    "create": "Example query for creating a new record.",
    "read": "Example query for reading a record.",
    "update": "Example query for updating a record.",
    "delete": "Example query for deleting a record."
  },
  "scalability_considerations": "Scalability considerations, especially for handling real-time data from the physical asset for the digital twin.",
  "performance_considerations": "Performance considerations for the digital twin's responsiveness.",
  "security_considerations": "Security considerations, including data access control and integrity for the digital twin.",
}

Begin designing the database for the specified application and its digital twin.
"""


    def generate_output(self, application_description, preferred_database_type="", model="default_model"):
        self.prompt = self.prompt_template.replace("{{application_description}}", application_description)
        self.prompt = self.prompt_template.replace("{{preferred_database_type}}", preferred_database_type)
        print("*")
        print("Database Configuration Agent Working (Обобщенный)")
        print("*")
        print("Prompt:\n", self.prompt)

        try:
            text_output = _model_call(self.prompt, model=model)
        except Exception as e:
            print(f"Error: {e}")
            return None

        try:
            result_json = json.loads(text_output)
        except json.JSONDecodeError as json_err:
            print(f"JSON Decode Error: {json_err}")
            return None

        with open('database_configuration_agent.json', 'w') as file:
            json.dump(result_json, file, indent=4)
        print("Result:\n")
        print(text_output)
        return result_json

