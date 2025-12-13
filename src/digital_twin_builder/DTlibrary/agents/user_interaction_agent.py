from digital_twin_builder.DTlibrary.agents.base_agent import BaseAgent
from typing import List, Dict


class UserInteractionAgent(BaseAgent):

    def __init__(self):
        super().__init__("UserInteractionAgent")

        self.topics = {
            "general_info": "Общая информация о предприятии",
            "production_processes": "Производственные процессы",
            "data_monitoring": "Данные и мониторинг",
            "twin_requirements": "Требования к цифровому двойнику",
        }

        self.current_topic = "general_info"
        self.completed_topics = []
        self.collected_data = {key: [] for key in self.topics}

        self.messages: List[Dict[str, str]] = []

        self.system_prompt = """
Ты — агент-интервьюер для создания цифрового двойника. 
Твоя задача — провести последовательное интервью по четырём темам.

Темы:
1. Общая информация о предприятии
2. Производственные процессы
3. Данные и мониторинг
4. Требования к цифровому двойнику

Для каждой темы:
- задавай вопросы,
- уточняй детали,
- когда информации достаточно, кратко суммируй,
- и переходи к следующей теме.

Когда все темы завершены:
- выдай полностью собранную информацию в JSON формате,
- ключи: general_info, production_processes, data_monitoring, twin_requirements,
- значения: списки строк,
- НЕ добавляй никакого текста вокруг JSON.

Разговор веди естественно, на русском языке.
"""

        self.messages.append({"role": "system", "content": self.system_prompt})


    def run(self):
        """Запускает интервью, возвращает первое сообщение."""

        greeting = (
            "Здравствуйте! Мы начнём интервью по созданию цифрового двойника.  \n"
            f"Первая тема: {self.topics[self.current_topic]}.  \n"
            "Пожалуйста, расскажите подробнее."
        )

        self.messages.append({"role": "assistant", "content": greeting})
        return greeting


    def next_step(self, user_text: str):

        self.messages.append({"role": "user", "content": user_text})

        self.collected_data[self.current_topic].append(user_text)

        context = "\n".join(
            [f"{m['role']}: {m['content']}" for m in self.messages]
        )

        prompt = (
            context
            + f"\nassistant: Ты сейчас работаешь с темой: {self.topics[self.current_topic]}.\n"
            + "Продолжай диалог или завершай тему, если информации достаточно.\n"
        )

        response = self.llm.generate(prompt).strip()

        self.messages.append({"role": "assistant", "content": response})

        lower = response.lower()
        if "следующ" in lower or "перейд" in lower:
            self.completed_topics.append(self.current_topic)

            remaining = [t for t in self.topics if t not in self.completed_topics]

            if remaining:
                self.current_topic = remaining[0]
            else:
                final_json = self._build_final_json()

                self.messages.append({
                    "role": "assistant",
                    "content": final_json
                })

                return final_json

        return response


    def is_finished(self):
        return len(self.completed_topics) == len(self.topics)


    def _build_final_json(self):
        import json

        return json.dumps(self.collected_data, ensure_ascii=False, indent=2)
