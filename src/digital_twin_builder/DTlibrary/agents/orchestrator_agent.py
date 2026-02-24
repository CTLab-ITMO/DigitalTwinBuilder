# orchestrator_agent.py
# Центральный мета-агент для маршрутизации задач между профильными агентами и сенсорами.
# Поддерживает Online RL (reward: расхождение симуляция/реальность, скорость адаптации, стоимость вызовов).
# Оптимизировано под NVIDIA Nemotron-Orchestrator-8B (XML-теги и JSON-схемы инструментов).

from .base_agent import BaseAgent
import json
import logging
import time
import re
from typing import Dict, Any, Optional, List, Tuple

# Заглушки для отложенного импорта (избегаем циклических зависимостей)
# from transformers import AutoModelForCausalLM, AutoTokenizer
# from cores.sensor_manager import SensorManager

# --- Описание инструментов в формате JSON Schema (как ожидает Nemotron-Orchestrator-8B) ---
ORCHESTRATOR_TOOLS_JSON = [
    {
        "name": "user_interaction",
        "description": "Проведение интервью с пользователем о производстве. Направляет сообщение агенту взаимодействия.",
        "parameters": {
            "type": "object", 
            "properties": {
                "conversation_id": {"type": "string"}, 
                "user_message": {"type": "string"}
            },
            "required": ["conversation_id"]
        }
    },
    {
        "name": "database_agent",
        "description": "Генерация схемы БД по результатам интервью.",
        "parameters": {
            "type": "object", 
            "properties": {
                "conversation_id": {"type": "string"}, 
                "interview_result": {"type": "string"}
            },
            "required": ["conversation_id", "interview_result"]
        }
    },
    {
        "name": "digital_twin_agent",
        "description": "Конфигурация цифрового двойника.",
        "parameters": {
            "type": "object", 
            "properties": {
                "requirements": {"type": "string"}, 
                "db_schema": {"type": "string"}
            },
            "required": ["requirements", "db_schema"]
        }
    },
    {
        "name": "ipcamera_gige",
        "description": "Работа с камерой GigE Vision (запуск, остановка, поиск).",
        "parameters": {
            "type": "object", 
            "properties": {
                "action": {"type": "string", "enum": ["start_stream", "stop_stream", "discovery"]}, 
                "camera_ip": {"type": "string"}, 
                "my_ip": {"type": "string"}, 
                "streaming_port": {"type": "integer"}
            },
            "required": ["action", "camera_ip"]
        }
    },
    {
        "name": "ipcamera_rtsp",
        "description": "Работа с RTSP-камерой.",
        "parameters": {
            "type": "object", 
            "properties": {
                "action": {"type": "string", "enum": ["connect", "disconnect"]}, 
                "rtsp_url": {"type": "string"}
            },
            "required": ["action", "rtsp_url"]
        }
    },
    {
        "name": "sensor_manager",
        "description": "Получение текущих или исторических данных с датчиков (температура, вибрация, давление и т.д.).",
        "parameters": {
            "type": "object", 
            "properties": {
                "action": {"type": "string", "enum": ["get_data", "get_last"]}
            },
            "required": ["action"]
        }
    },
    {
        "name": "finish",
        "description": "Используй этот инструмент для завершения цепочки рассуждений и возврата итогового ответа.",
        "parameters": {
            "type": "object", 
            "properties": {
                "result": {"type": "string", "description": "Итоговый ответ или вердикт для пользователя"}
            },
            "required": ["result"]
        }
    }
]


class OrchestratorAgent(BaseAgent):
    """
    Мета-агент: маршрутизирует высокоуровневые запросы между профильными агентами.
    Использует строгие XML-теги и JSON схемы для управления LLM.
    """

    ORCHESTRATOR_AGENT_ID = 0  # Центральная точка входа

    def __init__(
        self,
        agent_id: int = 0,
        api_url: str = "http://localhost:8000",
        model_name: str = "nvidia/Nemotron-Orchestrator-8B", 
        max_tool_steps: int = 10,
        use_sensor_manager: bool = False,
    ):
        super().__init__("OrchestratorAgent")
        self.agent_id = agent_id or self.ORCHESTRATOR_AGENT_ID
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name
        self.max_tool_steps = max_tool_steps
        self.running = False
        self._model = None
        self._tokenizer = None
        self._sensor_manager: Optional[Any] = None
        self.use_sensor_manager = use_sensor_manager

        # Подключение сенсоров для Online RL (reward)
        if use_sensor_manager:
            self._init_sensor_manager()

        self._step_count = 0
        self._llm_call_count = 0

    def _init_sensor_manager(self) -> None:
        """Lazy init sensor_manager для доступа к данным при расчёте reward."""
        try:
            from ..cores.sensor_manager import SensorManager
            self._sensor_manager = SensorManager(mode="sim")
        except ImportError as e:
            self.log(f"SensorManager not available: {e}", "warning")

    def _load_model(self) -> None:
        """Отложенная загрузка модели."""
        if self._model is not None:
            return
        # try:
        #     import torch
        #     from transformers import AutoModelForCausalLM, AutoTokenizer
        #     self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        #     self._model = AutoModelForCausalLM.from_pretrained(self.model_name)
        #     device = "cuda" if torch.cuda.is_available() else "cpu"
        #     self._model = self._model.to(device)
        # except Exception as e:
        #     self.log(f"Model load failed: {e}", "error")
        #     raise
        self.log("Model loading disabled (stub). Set _model manually or uncomment _load_model.", "warning")

    def _build_state(
        self,
        conversation_id: Optional[str] = None,
        messages: Optional[List[Dict]] = None,
        sensor_readings: Optional[Dict] = None,
        task_params: Optional[Dict] = None,
    ) -> str:
        """Собирает состояние в формате ChatML + XML, который ожидает Nemotron-Orchestrator-8B."""
        
        system_prompt = (
            "You are an expert orchestrator agent managing a factory Digital Twin.\n"
            "You may call one or more functions to assist with the user query.\n\n"
            "You are provided with function signatures within <tools></tools> XML tags:\n"
            "<tools>\n"
            f"{json.dumps(ORCHESTRATOR_TOOLS_JSON, ensure_ascii=False, indent=2)}\n"
            "</tools>\n\n"
            "For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n"
            "<tool_call>\n"
            '{"name": "<function-name>", "arguments": <args-json-object>}\n'
            "</tool_call>\n"
        )

        prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        
        # История диалога
        if messages:
            for m in messages[-10:]:
                role = m.get("role", "user")
                content = m.get("content", "")
                prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
        
        # Текущий запрос и состояние сенсоров
        current_context = f"Текущие показания датчиков: {json.dumps(sensor_readings, ensure_ascii=False) if sensor_readings else 'Нет данных'}\n"
        current_context += f"Запрос пользователя: {task_params.get('request', '')}"
        
        prompt += f"<|im_start|>user\n{current_context}<|im_end|>\n<|im_start|>assistant\n"
        return prompt

    def _generate(self, prompt: str) -> str:
        """Заглушка для инференса модели. Заменить на реальный model.generate()"""
        # Здесь должен быть реальный вызов LLM:
        # inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        # outputs = self._model.generate(**inputs, max_new_tokens=512)
        # return self._tokenizer.decode(outputs[0][inputs.input_ids.shape[-1]:])
        
        # Симуляция ответа модели для тестирования пайплайна
        return '<think>Мне нужно запросить профильного агента для ответа.</think>\n<tool_call>{"name": "finish", "arguments": {"result": "Система перенаправила ваш запрос."}}</tool_call>'

    def _parse_tool_call(self, raw_output: str) -> Optional[Dict[str, Any]]:
        """Парсит JSON-вызов инструмента из XML-тега <tool_call>, извлекая рассуждения из <think>."""
        think_match = re.search(r"<think>(.*?)</think>", raw_output, re.DOTALL)
        reasoning = think_match.group(1).strip() if think_match else ""

        call_match = re.search(r"<tool_call>\s*({.*?})\s*</tool_call>", raw_output, re.DOTALL)
        if not call_match:
            return None
            
        try:
            call_data = json.loads(call_match.group(1))
            return {
                "tool": call_data.get("name"),
                "args": call_data.get("arguments", {}),
                "reasoning": reasoning
            }
        except json.JSONDecodeError:
            self.log("Failed to parse tool call JSON", "error")
            return None

    def _execute_tool(self, tool_call: Dict[str, Any], context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Выполняет вызов инструмента. Возвращает (result_text_для_модели, metadata_для_reward)."""
        tool = tool_call.get("tool", "").strip()
        args = tool_call.get("args", {})
        metadata = {"tool": tool, "latency_ms": 0, "success": False}

        t0 = time.perf_counter()
        result = ""

        if tool == "finish":
            result = args.get("result", "Готово.")
            metadata["success"] = True

        elif tool == "user_interaction":
            result = "[stub] user_interaction: делегировано агенту 1"
            metadata["success"] = True

        elif tool == "database_agent":
            result = "[stub] database_agent: делегировано агенту 2"
            metadata["success"] = True

        elif tool == "digital_twin_agent":
            result = "[stub] digital_twin_agent: конфигурация сгенерирована"
            metadata["success"] = True

        elif tool == "ipcamera_gige":
            result = "[stub] ipcamera_gige: действие выполнено"
            metadata["success"] = True

        elif tool == "ipcamera_rtsp":
            result = "[stub] ipcamera_rtsp: действие не выполнено"
            metadata["success"] = False

        elif tool == "sensor_manager":
            if self._sensor_manager:
                data = self._sensor_manager.get_data()
                result = json.dumps(data, ensure_ascii=False) if data else "{}"
                metadata["success"] = True
            else:
                result = "Ошибка: SensorManager недоступен"
                metadata["success"] = False
        else:
            result = f"Ошибка: Неизвестный инструмент {tool}"

        metadata["latency_ms"] = (time.perf_counter() - t0) * 1000
        return result, metadata

    def compute_reward(
        self,
        tool_metadata: List[Dict],
        sensor_sim_vs_real: Optional[Dict] = None,
        outcome_success: bool = True,
    ) -> float:
        """Функция вознаграждения для Online RL."""
        sim_divergence = 0.0
        if sensor_sim_vs_real:
            for k, v in sensor_sim_vs_real.items():
                if isinstance(v, (int, float)):
                    sim_divergence += abs(v)
        sim_divergence_penalty = -0.1 * sim_divergence

        compute_cost = -0.01 * self._llm_call_count
        step_penalty = -0.05 * len(tool_metadata)

        adaptation_bonus = 1.0 if outcome_success else -1.0
        success_bonus = 0.1 * sum(1 for m in tool_metadata if m.get("success")) - 0.2 * sum(
            1 for m in tool_metadata if not m.get("success")
        )

        reward = sim_divergence_penalty + compute_cost + step_penalty + adaptation_bonus + success_bonus
        return round(reward, 4)

    def route_request(
        self,
        high_level_request: str,
        conversation_id: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Цикл оркестратора: принимает запрос, генерирует действия, выполняет их,
        кормит результаты обратно в модель, пока не будет вызван 'finish'.
        """
        self._step_count = 0
        self._llm_call_count = 0
        steps = []
        context = context or {}
        
        sensor_readings = None
        if self._sensor_manager:
            raw_readings = self._sensor_manager.get_data()
            if raw_readings:
                sensor_readings = raw_readings.get("sensor_data", {})

        # 1. Формируем стартовый промпт
        prompt = self._build_state(
            conversation_id=conversation_id,
            messages=context.get("messages", []),
            sensor_readings=sensor_readings,
            task_params={"request": high_level_request, **context},
        )

        self._load_model()

        # 2. Основной цикл выполнения (Loop)
        for _ in range(self.max_tool_steps):
            raw_output = self._generate(prompt)
            self._llm_call_count += 1
            
            # Добавляем ответ модели в контекст
            prompt += f"{raw_output}<|im_end|>\n"
            
            tool_call = self._parse_tool_call(raw_output)
            
            if not tool_call:
                # Если модель не сгенерировала валидный инструмент, прерываем цикл
                steps.append({"tool": "none", "result_preview": raw_output})
                break
                
            if tool_call.get("tool") == "finish":
                steps.append({"tool": "finish", "result": tool_call.get("args", {}).get("result", "")})
                break

            # Выполняем запрошенный инструмент
            result, meta = self._execute_tool(tool_call, context)
            steps.append({**meta, "reasoning": tool_call.get("reasoning", ""), "result_preview": str(result)[:200]})

            # Возвращаем результат выполнения модели через специальный тег <tool_response>
            prompt += f"<tool_response>\n{result}\n</tool_response>\n<|im_start|>assistant\n"

        reward = self.compute_reward(steps, sensor_readings, outcome_success=(len(steps) > 0 and steps[-1].get("tool") == "finish"))

        return {
            "result": steps[-1].get("result", steps[-1].get("result_preview", "")) if steps else "",
            "steps": steps,
            "reward": reward,
            "llm_calls": self._llm_call_count,
        }

    def process_task(self, task: Dict[str, Any]) -> str:
        params = task.get("params", {})
        conversation_id = task.get("conversation_id", "")
        request = params.get("request", params.get("user_message", "Обработать запрос"))

        out = self.route_request(
            high_level_request=request,
            conversation_id=conversation_id,
            context=params,
        )
        return json.dumps(out, ensure_ascii=False, indent=2)

def main():
    import argparse
    import signal
    import sys

    parser = argparse.ArgumentParser(description="Orchestrator Agent")
    parser.add_argument("--agent-id", type=int, default=0)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--model", default="nvidia/Nemotron-Orchestrator-8B")
    parser.add_argument("--use-sensors", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    args = parser.parse_args()

    agent = OrchestratorAgent(
        agent_id=args.agent_id,
        api_url=args.api_url,
        model_name=args.model,
        use_sensor_manager=args.use_sensors,
    )

    def on_signal(sig, frame):
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    agent.run(interval=args.poll_interval)

if __name__ == "__main__":
    main()
