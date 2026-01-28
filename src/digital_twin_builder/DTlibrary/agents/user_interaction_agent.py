from digital_twin_builder.DTlibrary.agents.base_agent import BaseAgent
import json
from typing import Dict, List, Any


class UserInteractionAgent(BaseAgent):
    def __init__(self):
        super().__init__("UserInteractionAgent")
        self.system_prompt = """Ты — эксперт-консультант по созданию цифровых двойников для промышленных производств.

Твоя задача — провести интервью с пользователем, чтобы собрать всю необходимую информацию для построения цифрового двойника.

Ты должен:
1. Задавать вопросы о производстве, процессах, оборудовании
2. Уточнять детали о датчиках, параметрах, которые нужно отслеживать
3. Выяснять цели создания цифрового двойника
4. Понимать, какие данные доступны и как часто они обновляются
5. Собирать информацию о критических параметрах и пороговых значениях

Веди диалог естественно, задавай от 1 до 3 вопросов за раз. Не перегружай пользователя.

Когда ты соберешь достаточно информации для построения цифрового двойника, сообщи об этом,
резюмируй собранную информацию и спроси, всё ли правильно понято.

ВАЖНО: Отвечай только на русском языке. Общайся дружелюбно и профессионально."""

    def run(self, user_message: str, chat_history: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Обрабатывает сообщение пользователя и возвращает ответ от агента.
        
        Args:
            user_message: текущее сообщение пользователя
            chat_history: полная история чата
            
        Returns:
            Dict с ключами:
                - message: ответ агента
                - completed: флаг завершения интервью (bool)
                - requirements: собранные требования (dict, если completed=True)
        """
        try:
            self.log(f"Обработка сообщения пользователя: {user_message[:100]}...")
            
            conversation_context = self._build_conversation_context(chat_history)
            
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

            
            response_text = self.llm.generate(
                prompt=prompt,
                system_prompt=self.system_prompt,
                max_tokens=1024
            )
            
            try:
                cleaned_response = response_text.strip()
                
                if cleaned_response.startswith("```json"):
                    cleaned_response = cleaned_response.replace("```json", "", 1)
                if cleaned_response.startswith("```"):
                    cleaned_response = cleaned_response.replace("```", "", 1)
                if cleaned_response.endswith("```"):
                    cleaned_response = cleaned_response.rsplit("```", 1)[0]
                
                cleaned_response = cleaned_response.strip()
                
                response_json = json.loads(cleaned_response)
                self.log("Успешно распарсили JSON ответ от LLM")
                return response_json
            except json.JSONDecodeError as e:
                
                self.log(f"Не удалось распарсить JSON: {str(e)}", "warning")
                self.log(f"Оригинальный ответ: {response_text[:200]}...", "warning")
                return {
                    "completed": False,
                    "message": response_text
                }
                
        except Exception as e:
            self.log(f"Ошибка в run: {str(e)}", "error")
            return {
                "completed": False,
                "message": "Извините, произошла ошибка при обработке вашего сообщения. Попробуйте переформулировать."
            }

    def _build_conversation_context(self, chat_history: List[Dict[str, str]], max_messages: int = 10) -> str:
        """Строит контекст разговора из истории чата"""
        
        recent_history = chat_history[-max_messages:] if len(chat_history) > max_messages else chat_history
        
        context_lines = []
        for msg in recent_history:
            role = "Ассистент" if msg["role"] == "assistant" else "Пользователь"
            context_lines.append(f"{role}: {msg['content']}")
        
        return "\n".join(context_lines)

    def extract_requirements(self, chat_history: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Извлекает структурированные требования из истории чата.
        Используется как запасной вариант, если LLM не вернул requirements.
        """
        prompt = f"""На основе следующей истории разговора с пользователем,
извлеки и структурируй всю информацию о производстве для создания цифрового двойника.

История разговора:
{self._build_conversation_context(chat_history, max_messages=20)}

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

        try:
            response = self.llm.generate(
                prompt=prompt,
                system_prompt="You are a requirements extraction expert. Extract information and return only valid JSON.",
                max_tokens=1024
            )
            
            requirements = json.loads(response.strip())
            return requirements
        except Exception as e:
            self.log(f"Ошибка извлечения требований: {str(e)}", "error")
            
            return {
                "production_type": "Не указано",
                "processes": [],
                "equipment": [],
                "sensors": [],
                "goals": "Не указано",
                "data_sources": "Не указано",
                "update_frequency": "Не указано",
                "critical_parameters": {},
                "additional_info": "Информация из чата"
            }