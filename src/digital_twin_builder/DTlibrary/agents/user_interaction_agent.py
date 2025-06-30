from .base_agent import BaseAgent
from transformers import pipeline
import json

class UserInteractionAgent(BaseAgent):
    def __init__(self):
        super().__init__("UserInteractionAgent")
        try:
            self.model = pipeline("text-generation", model="MTSAIR/Cotype-Nano")
        except Exception as e:
            self.log(f"Model loading failed: {str(e)}", "error")
            raise
        
        self.interview_template = self.interview_template = """Ты - агент для сбора информации о металлургическом производстве с целью создания цифрового двойника. Проведи интервью на русском языке, задавая четкие вопросы по следующим темам:

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
            response = self.model(
                self.interview_template,
                max_length=2048,
                num_return_sequences=1
            )[0]['generated_text']
            
            return json.loads(response)
        except json.JSONDecodeError:
            return {"response": response}
        except Exception as e:
            self.log(f"Interview failed: {str(e)}", "error")
            raise