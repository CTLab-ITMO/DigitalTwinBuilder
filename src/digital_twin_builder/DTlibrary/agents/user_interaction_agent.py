from digital_twin_builder.DTlibrary.agents.base_agent import BaseAgent
import json
from typing import Dict, List, Any


class UserInteractionAgent(BaseAgent):
    def __init__(self, language: str = "ru"):
        super().__init__("UserInteractionAgent")
        self.language = language
        self.update_prompts()

    def set_language(self, language: str):
        self.language = language
        self.update_prompts()

    def update_prompts(self):
        if self.language == "ru":
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
        else:  
            self.system_prompt = """You are an expert consultant in creating digital twins for industrial production.

Your task is to conduct an interview with the user to gather all necessary information for building a digital twin.

You should:
1. Ask questions about production, processes, equipment
2. Clarify details about sensors, parameters that need to be monitored
3. Find out the goals of creating the digital twin
4. Understand what data is available and how often it is updated
5. Gather information about critical parameters and threshold values

Conduct the dialogue naturally, ask 1 to 3 questions at a time. Don't overload the user.

When you have gathered enough information to build a digital twin, inform about it,
summarize the collected information and ask if everything is understood correctly.

IMPORTANT: Respond only in English. Communicate in a friendly and professional manner."""

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
            
            if self.language == "ru":
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
            else:  
                prompt = f"""Conversation history:
{conversation_context}

User: {user_message}

Analyze the user's response. If there is enough information to create a digital twin, return JSON:
{{
    "completed": true,
    "requirements": {{
        "production_type": "production type description",
        "processes": ["list of processes"],
        "equipment": ["list of equipment"],
        "sensors": ["list of sensors and parameters"],
        "goals": "digital twin creation goals",
        "data_sources": "data sources description",
        "update_frequency": "data update frequency",
        "critical_parameters": {{"parameter": "threshold_value"}},
        "additional_info": "any additional important information"
    }},
    "message": "your response to the user, summarize the collected information"
}}

If there is NOT enough information, return JSON:
{{
    "completed": false,
    "message": "your response with clarifying questions"
}}

IMPORTANT: Return ONLY valid JSON without markdown formatting, without code blocks (```), without explanations. Start immediately with the opening curly brace {{."""

            
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
            error_messages = {
                "ru": "Извините, произошла ошибка при обработке вашего сообщения. Попробуйте переформулировать.",
                "en": "Sorry, an error occurred while processing your message. Please try to rephrase."
            }
            return {
                "completed": False,
                "message": error_messages.get(self.language, error_messages["ru"])
            }

    def _build_conversation_context(self, chat_history: List[Dict[str, str]], max_messages: int = 10) -> str:
        """Строит контекст разговора из истории чата"""
        
        recent_history = chat_history[-max_messages:] if len(chat_history) > max_messages else chat_history
        
        context_lines = []
        role_names = {
            "ru": {"assistant": "Ассистент", "user": "Пользователь"},
            "en": {"assistant": "Assistant", "user": "User"}
        }
        
        for msg in recent_history:
            role = role_names[self.language].get(msg["role"], msg["role"])
            context_lines.append(f"{role}: {msg['content']}")
        
        return "\n".join(context_lines)

    def extract_requirements(self, chat_history: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Извлекает структурированные требования из истории чата.
        Используется как запасной вариант, если LLM не вернул requirements.
        """
        if self.language == "ru":
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
        else:  
            prompt = f"""Based on the following conversation history with the user,
extract and structure all production information for creating a digital twin.

Conversation history:
{self._build_conversation_context(chat_history, max_messages=20)}

Return JSON with the following structure:
{{
    "production_type": "production type",
    "processes": ["list of processes"],
    "equipment": ["list of equipment"],
    "sensors": ["list of sensors and parameters"],
    "goals": "digital twin creation goals",
    "data_sources": "data sources",
    "update_frequency": "update frequency",
    "critical_parameters": {{"parameter": "value"}},
    "additional_info": "additional information"
}}

Return ONLY valid JSON."""

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
            
            default_values = {
                "ru": {
                    "production_type": "Не указано",
                    "processes": [],
                    "equipment": [],
                    "sensors": [],
                    "goals": "Не указано",
                    "data_sources": "Не указано",
                    "update_frequency": "Не указано",
                    "critical_parameters": {},
                    "additional_info": "Информация из чата"
                },
                "en": {
                    "production_type": "Not specified",
                    "processes": [],
                    "equipment": [],
                    "sensors": [],
                    "goals": "Not specified",
                    "data_sources": "Not specified",
                    "update_frequency": "Not specified",
                    "critical_parameters": {},
                    "additional_info": "Information from chat"
                }
            }
            
            return default_values.get(self.language, default_values["ru"])