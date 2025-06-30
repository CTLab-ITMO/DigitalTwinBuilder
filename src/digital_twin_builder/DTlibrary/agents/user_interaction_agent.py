from .base_agent import BaseAgent
from transformers import pipeline, AutoModelForCausalLM, AutoTokenizer
import torch
import logging
from typing import Dict, Any

class UserInteractionAgent(BaseAgent):
    def __init__(self):
        super().__init__("UserInteractionAgent")
        self.model = None
        self.tokenizer = None
        self._load_model()  
        
        self.system_prompt = """
        Ты — AI-ассистент для сбора информации о металлургическом производстве. 
        Задавай вопросы по следующим темам:
        1. Общая информация о предприятии
        2. Производственные процессы
        3. Используемые датчики и данные
        4. Требования к цифровому двойнику

        **Правила:**
        - Начни с приветствия и объясни цель.
        - Задавай вопросы по одному.
        - Уточняй, если ответ непонятен.
        - В конце суммируй информацию.
        """

    def _load_model(self):
        try:
            self.tokenizer = AutoTokenizer.from_pretrained("MTSAIR/Cotype-Nano")
            self.model = AutoModelForCausalLM.from_pretrained(
                "MTSAIR/Cotype-Nano",
                device_map="auto" if torch.cuda.is_available() else "cpu",
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
            )
            self.log("Cotype-Nano успешно загружена.", "info")
        except Exception as e:
            self.log(f"Ошибка загрузки модели: {e}", "error")
            raise RuntimeError("Не удалось загрузить Cotype-Nano. Проверьте интернет или наличие модели в Hugging Face.")

    def generate_question(self, context: str = "") -> str:
        prompt = f"""
        {self.system_prompt}
        Контекст: {context}
        Следующий вопрос:
        """
        
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=100,
                temperature=0.7,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id
            )
        
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        return response.split("Следующий вопрос:")[-1].strip()

    def conduct_interview(self) -> Dict[str, Any]:
        try:
            first_question = self.generate_question("Начни интервью.")
            return {
                "initial_response": first_question,
                "system_prompt": self.system_prompt
            }
        except Exception as e:
            self.log(f"Ошибка запуска интервью: {e}", "error")
            raise