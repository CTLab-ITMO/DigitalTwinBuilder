from .base_agent import BaseAgent
from transformers import pipeline
import json
from typing import Dict, Any

class UserInteractionAgent(BaseAgent):
    def __init__(self):
        super().__init__("UserInteractionAgent")
        try:
            self.model = pipeline("text-generation", model="MTSAIR/Cotype-Nano")
        except Exception as e:
            self.log(f"Model loading failed: {str(e)}", "error")
            raise
        
        self.system_prompt = """Ты - агент для сбора информации о производстве с целью создания цифрового двойника. Проведи интервью на русском языке, задавая четкие вопросы по следующим темам:

1. Общая информация о предприятии:
   - Основная деятельность и продукция
   - Организационная структура
   - Площади производства

2. Производственные процессы:
   - Основные технологические этапы
   - Критическое оборудование
   - Проблемные участки

3. Данные и мониторинг:
   - Используемые датчики и их параметры
   - Системы сбора данных
   - Текущие показатели эффективности

4. Требования к цифровому двойнику:
   - Какие процессы нужно моделировать
   - Какие показатели отслеживать
   - Интеграция с существующими системами

Веди диалог естественно, уточняй непонятные моменты. В конце представь собранную информацию в виде JSON структуры на русском языке."""

    def run(self, input_data=None):
        try:
            return self.conduct_interview()
        except Exception as e:
            self.log(f"Error in run method: {str(e)}", "error")
            raise

    def conduct_interview(self):
        self.log("Starting digital twin configuration interview with LLM")
        try:
            initial_prompt = f"{self.system_prompt}\n\nНачни диалог с приветствия и краткого перечисления пунктов, которые нужно обсудить."
            response = self.model(
                initial_prompt,
                max_length=2048,
                num_return_sequences=1
            )[0]['generated_text']
            
            assistant_response = response.replace(self.system_prompt, "").strip()
            
            return {
                "initial_response": assistant_response,
                "system_prompt": self.system_prompt
            }
        except Exception as e:
            self.log(f"Interview failed: {str(e)}", "error")
            raise