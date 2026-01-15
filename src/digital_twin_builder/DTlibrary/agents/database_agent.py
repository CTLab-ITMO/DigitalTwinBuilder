from digital_twin_builder.DTlibrary.agents.base_agent import BaseAgent
import json
from typing import Dict, Any

class DatabaseAgent(BaseAgent):
    def __init__(self):
        super().__init__("DatabaseAgent")
        self.system_prompt = ("Ты — эксперт по проектированию баз данных SQL. "
                              "На основе требований к цифровому двойнику промышленного производства, "
                              "сгенерируй схему базы данных PostgreSQL в формате JSON. "
                              "JSON должен содержать таблицы, столбцы, типы данных, ограничения и связи. "
                              "Ответ должен быть только валидным JSON-объектом, без пояснений.")

    def run(self, requirements: Dict[str, Any] = None) -> Dict[str, Any]:
        try:
            if not requirements:
                raise ValueError("Требования для генерации схемы БД не предоставлены.")

            self.log("Запуск генерации схемы БД с помощью LLM.")
            schema_json = self.generate_schema(requirements)
            return schema_json
        except Exception as e:
            self.log(f"Ошибка в методе run: {str(e)}", "error")
            raise

    def generate_schema(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""
        Сгенерируй схему базы данных PostgreSQL для цифрового двойника промышленного производства на основе следующих требований:

        {json.dumps(requirements, ensure_ascii=False, indent=2)}

        Схема должна включать таблицы для:
        - Данных с датчиков (температура, давление, вибрация, уровень и т.д.)
        - Статуса оборудования
        - Метрик качества производства
        - Состава материалов
        - Истории обслуживания (опционально)
        - Событий/алертов (опционально)

        Ответ должен быть представлен в виде валидного JSON-объекта с описанием таблиц, столбцов, типов данных, ограничений и связей.
        """

        try:
            result = self.llm.generate_json(prompt, system_prompt=self.system_prompt, max_tokens=2048)
            
            if isinstance(result, dict):
                if 'raw' in result:
                    raw_text = result['raw']
                    try:
                        parsed_json = json.loads(raw_text)
                        return parsed_json
                    except json.JSONDecodeError:
                        return {"error": "Не удалось распарсить сгенерированный JSON", "raw_output": raw_text}
                else:
                    return result
            else:
                return {"error": "Непредвиденный формат результата от LLM", "output": str(result)}

        except Exception as e:
            self.log(f"Ошибка при генерации схемы: {str(e)}", "error")
            raise


    def interpret_schema(self, schema_json: Dict[str, Any]) -> str:
        """ Генерирует текстовое описание схемы БД для пользователя. """
        prompt = f"""
        Дана сгенерированная схема базы данных для цифрового двойника:
        {json.dumps(schema_json, ensure_ascii=False, indent=2)}

        Напиши краткое текстовое описание этой схемы, объясняя какие таблицы и для чего созданы, какие данные они будут хранить. Используй простой и понятный язык. Выводи только это описание, без своих комментариев.
        """
        try:
            interpretation = self.llm.generate(prompt, system_prompt="", max_tokens=512)
            return interpretation
        except Exception as e:
            self.log(f"Ошибка при интерпретации схемы: {str(e)}", "error")
            return "Не удалось сгенерировать описание схемы."