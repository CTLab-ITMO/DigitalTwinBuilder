# orchestrator_agent.py
# Центральный мета-агент для маршрутизации задач между профильными агентами и сенсорами.
# Заготовка для интеграции Online RL (reward: расхождение симуляция/реальность, скорость адаптации, стоимость вызовов).
# Модель: NVIDIA Orchestrator-8B / ToolOrchestra (JSON-вызовы инструментов).

from .base_agent import BaseAgent
import json
import logging
import time
from typing import Dict, Any, Optional, List, Tuple

# Заглушки для отложенного импорта (избегаем циклических зависимостей)
# from transformers import AutoModelForCausalLM, AutoTokenizer
# from cores.sensor_manager import SensorManager


# --- Описание инструментов для системного промпта (Prompt Engineering) ---
ORCHESTRATOR_TOOLS = """
## Доступные инструменты

1. **user_interaction** (agent_id=1)
   - Назначение: Проведение интервью с пользователем о производстве
   - Вызов: user_interaction(conversation_id, user_message?)
   - Возвращает: ответ агента для продолжения диалога

2. **database_agent** (agent_id=2)
   - Назначение: Генерация схемы БД по результатам интервью
   - Вызов: database_agent(conversation_id, interview_result)
   - Возвращает: SQL/JSON-схема базы данных

3. **digital_twin_agent** (agent_id=3)
   - Назначение: Конфигурация цифрового двойника
   - Вызов: digital_twin_agent(requirements, db_schema)
   - Возвращает: JSON-конфигурация компонентов двойника

4. **ipcamera_gige**
   - Назначение: Работа с камерой GigE Vision
   - Вызов: ipcamera_gige(action="start_stream"|"stop_stream", camera_ip, my_ip, streaming_port)
   - Альтернатива: ipcamera_gige(action="discovery", camera_ip)

5. **ipcamera_rtsp**
   - Назначение: Работа с RTSP-камерой
   - Вызов: ipcamera_rtsp(action="connect"|"disconnect", rtsp_url)

6. **sensor_manager**
   - Назначение: Получение данных с датчиков (температура, вибрация, давление и т.д.)
   - Вызов: sensor_manager(action="get_data"|"get_last")
   - Возвращает: {timestamp, sensor_data: {...}}

## Формат ответа
Выводи только валидный JSON:
{"tool": "имя_инструмента", "args": {...}, "reasoning": "краткое обоснование"}
Для завершения цепочки: {"tool": "finish", "result": "итоговый ответ пользователю"}
"""


class OrchestratorAgent(BaseAgent):
    """
    Мета-агент: маршрутизирует высокоуровневые запросы между user_interaction,
    database_agent, digital_twin_agent, ipcamera и sensor_manager.
    Заготовка для Online RL: reward = f(sim_divergence, adaptation_speed, compute_cost).
    """

    ORCHESTRATOR_AGENT_ID = 0  # Центральная точка входа

    def __init__(
        self,
        agent_id: int = 0,
        api_url: str = "http://localhost:8000",
        model_name: str = "nvidia/Orchestrator-8B",  # или Qwen2.5-7B-Instruct для русского
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

        # Счётчики для reward (стоимость вызовов LLM)
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
        """Отложенная загрузка модели. Заглушка — раскомментировать при использовании."""
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
        """Собирает состояние для LLM: диалог + показания датчиков + контекст."""
        parts = [
            "## Текущее состояние",
            "Доступные инструменты:",
            ORCHESTRATOR_TOOLS,
        ]
        if messages:
            parts.append("\n## История диалога")
            for m in messages[-20:]:
                parts.append(f"{m.get('role', '?')}: {m.get('content', '')[:500]}")
        if sensor_readings:
            parts.append("\n## Показания датчиков (последние)")
            parts.append(json.dumps(sensor_readings, ensure_ascii=False, indent=2))
        if task_params:
            parts.append("\n## Параметры задачи")
            parts.append(json.dumps(task_params, ensure_ascii=False))
        return "\n".join(parts)

    def _parse_tool_call(self, raw_output: str) -> Optional[Dict[str, Any]]:
        """Парсит JSON-вызов инструмента из вывода модели."""
        try:
            start = raw_output.find("{")
            end = raw_output.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw_output[start:end])
        except json.JSONDecodeError:
            pass
        return None

    def _execute_tool(self, tool_call: Dict[str, Any], context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Выполняет вызов инструмента. Заглушка — реализовать вызовы к API/локальным агентам.
        Возвращает (result_text, metadata для reward).
        """
        tool = tool_call.get("tool", "").strip()
        args = tool_call.get("args", {})
        metadata = {"tool": tool, "latency_ms": 0, "success": False}

        t0 = time.perf_counter()
        result = ""

        if tool == "finish":
            result = tool_call.get("result", "Готово.")
            metadata["success"] = True

        elif tool == "user_interaction":
            # TODO: POST /tasks agent_id=1, conversation_id, params
            result = "[stub] user_interaction: делегировано агенту 1"
            metadata["success"] = True

        elif tool == "database_agent":
            # TODO: POST /tasks agent_id=2
            result = "[stub] database_agent: делегировано агенту 2"
            metadata["success"] = True

        elif tool == "digital_twin_agent":
            # TODO: вызов DigitalTwinAgent.configure_twin(requirements, db_schema)
            result = "[stub] digital_twin_agent: конфигурация сгенерирована"
            metadata["success"] = True

        elif tool == "ipcamera_gige":
            # TODO: from digital_twin_builder.ipcamera.camera.gige import gige; ...
            result = "[stub] ipcamera_gige: действие не выполнено"
            metadata["success"] = False

        elif tool == "ipcamera_rtsp":
            result = "[stub] ipcamera_rtsp: действие не выполнено"
            metadata["success"] = False

        elif tool == "sensor_manager":
            if self._sensor_manager:
                data = self._sensor_manager.get_data()
                result = json.dumps(data, ensure_ascii=False) if data else "{}"
                metadata["success"] = True
            else:
                result = "{}"
                metadata["success"] = True

        else:
            result = f"Неизвестный инструмент: {tool}"

        metadata["latency_ms"] = (time.perf_counter() - t0) * 1000
        return result, metadata

    def compute_reward(
        self,
        tool_metadata: List[Dict],
        sensor_sim_vs_real: Optional[Dict] = None,
        outcome_success: bool = True,
    ) -> float:
        """
        Функция вознаграждения для Online RL (заглушка).
        reward = -sim_divergence - compute_cost + adaptation_bonus.
        """
        # 1. Расхождение симуляция vs реальные датчики (штраф)
        sim_divergence = 0.0
        if sensor_sim_vs_real:
            for k, v in sensor_sim_vs_real.items():
                if isinstance(v, (int, float)):
                    sim_divergence += abs(v)
        sim_divergence_penalty = -0.1 * sim_divergence

        # 2. Стоимость вызовов (штраф за лишние шаги)
        compute_cost = -0.01 * self._llm_call_count
        step_penalty = -0.05 * len(tool_metadata)

        # 3. Скорость адаптации / успех (поощрение)
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
        Единая точка входа: принимает высокоуровневый запрос и распределяет между агентами.
        Возвращает {result, steps[], reward, error?}.
        """
        self._step_count = 0
        self._llm_call_count = 0
        steps = []
        context = context or {}
        messages = context.get("messages", [])
        sensor_readings = None
        if self._sensor_manager:
            sensor_readings = self._sensor_manager.get_data()
            if sensor_readings:
                sensor_readings = sensor_readings.get("sensor_data", {})

        state = self._build_state(
            conversation_id=conversation_id,
            messages=messages,
            sensor_readings=sensor_readings,
            task_params={"request": high_level_request, **context},
        )

        # Заглушка генерации (без модели)
        self._load_model()
        # prompt = f"{state}\n\nЗапрос пользователя: {high_level_request}\n\nТвой JSON-вызов:"
        # generated = self._generate(prompt)  # -> raw_output
        # tool_call = self._parse_tool_call(generated)

        # Имитация одного шага для демонстрации пайплайна
        tool_call = {
            "tool": "user_interaction",
            "args": {"conversation_id": conversation_id or "", "user_message": high_level_request},
            "reasoning": "Перенаправление на агента интервью",
        }
        self._llm_call_count += 1

        for _ in range(self.max_tool_steps):
            if not tool_call:
                break
            if tool_call.get("tool") == "finish":
                steps.append({"tool": "finish", "result": tool_call.get("result", "")})
                break

            result, meta = self._execute_tool(tool_call, context)
            steps.append({**meta, "result_preview": str(result)[:200]})

            # TODO: добавить result в messages и вызвать _generate снова
            # generated = self._generate(...)
            # tool_call = self._parse_tool_call(generated)
            tool_call = {"tool": "finish", "result": result}

        reward = self.compute_reward(steps, sensor_readings, outcome_success=len(steps) > 0)

        return {
            "result": steps[-1].get("result_preview", steps[-1].get("result", "")) if steps else "",
            "steps": steps,
            "reward": reward,
            "llm_calls": self._llm_call_count,
        }

    def process_task(self, task: Dict[str, Any]) -> str:
        """Реализация BaseAgent: обработка задачи из API (единая точка входа)."""
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
    """CLI: запуск оркестратора как API-агента."""
    import argparse
    import signal
    import sys

    parser = argparse.ArgumentParser(description="Orchestrator Agent")
    parser.add_argument("--agent-id", type=int, default=0)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--model", default="nvidia/Orchestrator-8B")
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
