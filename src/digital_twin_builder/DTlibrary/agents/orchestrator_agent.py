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
        "description": "Генерация схемы БД по результатам интервью и применение её к БД (CREATE TABLE, INSERT в devices/sensors). Вызывай, когда есть готовый результат интервью или артефакт для сохранения в БД. Возвращает статус и сгенерированный SQL.",
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
                "result": {
                    "type": "string",
                    "description": "Итоговый ответ или вердикт для пользователя ИЛИ высоко-структурированное действие/план в формате JSON."
                }
            },
            "required": ["result"]
        }
    }
]

# --- few-shot для Nemotron-Orchestrator-8B (CoT + tool_call JSON) ---

FEWSHOT_DIALOG = [
    {
        "role": "system",
        "content": (
            "Ты orchestrator_agent. Твоя задача:\n"
            "1. Решать, каких инструментов вызывать: user_interaction, database_agent, digital_twin_agent\n"
            "2. Передавать аргументы строго по сигнатурам:\n"
            "   - user_interaction: conversation_id (обязательно), user_message (опционально, строка)\n"
            "   - database_agent: conversation_id, interview_result (обязательно). Генерирует SQL-схему по результатам интервью и применяет её к БД (таблицы devices, sensors и данные).\n"
            "   - digital_twin_agent: requirements, db_schema (обязательно, обе строки — JSON или текст)\n"
            "3. Собирать результаты и выдавать пользователю через user_interaction (передай user_message с текстом ответа)\n\n"
            "ЛОГИКА:\n"
            "- Нужны уточнения или ответ пользователю → user_interaction(conversation_id, user_message)\n"
            "- Есть данные для проектирования ДТ → digital_twin_agent(requirements=..., db_schema=...)\n"
            "- Есть результат интервью или артефакт для сохранения в БД → database_agent(conversation_id, interview_result=...). Одна тула и генерирует схему, и применяет её к БД.\n"
            "- Готов финальный ответ → finish(result=...)\n\n"
            "НЕ генерируй текст для пользователя напрямую. Только tool calls с правильными именами и аргументами."
        )
    },

    # =============================================================================
    # TERN 1: User asks about sensors for filling line
    # =============================================================================
    {
        "role": "user",
        "content": (
            "У нас автоматическая линия розлива и укупорки бутылок с лимонадом. "
            "Хочу настроить систему датчиков, чтобы отслеживать: температуру продукта, давление в трубопроводе "
            "перед наливом и состояние привода конвейера. Пока думаю поставить датчики температуры, давления и "
            "влажности в цеху. Подскажи, какие датчики нужны и что лишнее."
        )
    },

    # Orchestrator → interview needed (user_interaction: conversation_id + user_message)
    {
        "role": "assistant", 
        "tool_calls": [
            {
                "id": "call_ui_interview_001",
                "type": "function",
                "function": {
                    "name": "user_interaction",
                    "arguments": {
                        "conversation_id": "conv_001",
                        "user_message": "линия розлива лимонада, датчики: temp продукта, давление перед наливом, конвейер, влажность цеха (?лишнее). Нужны уточняющие вопросы для подбора датчиков."
                    }
                }
            }
        ]
    },
    
    # user_interaction returns interview plan
    {
        "role": "tool",
        "tool_call_id": "call_ui_interview_001",
        "name": "user_interaction", 
        "content": (
            '{"questions":['
            '"В каком диапазоне температура продукта после пастеризатора/охладителя и перед наливом? Какие пороги \"плохо/авария\"?",'
            '"Какой рабочий диапазон давления перед наливом? Бывают ли скачки/пульсации?",'
            '"Как сейчас контролируете конвейер? Какие симптомы поломок (клин, вибрация, перегрев)?",'
            '"Влажность — есть ли реальные проблемы (конденсат, коррозия), или просто \"для наблюдения\"?"'
            '],'
            '"assumptions":["пищевая линия → нужны гигиенические датчики IP67+","конвейер клинит → нужна диагностика причин"],'
            '"missing_slots":["temp_ranges","pressure_ranges","drive_failure_modes","humidity_justification"]}'
        )
    },

    # Orchestrator → asks user questions (echo from user_interaction_agent result)
    {
        "role": "assistant",
        "content": (
            "Чтобы подобрать датчики без лишнего, уточню:\n"
            "1) Диапазон температуры продукта после пастеризатора и перед наливом? Какие пороги \"плохо\"?\n"
            "2) Рабочее давление перед наливом и бывают ли скачки?\n"
            "3) Как контролируете конвейер сейчас? Какие симптомы поломок?\n"
            "4) Влажность вызывает проблемы или просто хотите видеть?"
        )
    },

    # =============================================================================
    # TURN 2: User provides details  
    # =============================================================================
    {
        "role": "user",
        "content": (
            "Температура после пастеризатора обычно 6–8 °C, выше 12 °C уже плохо. "
            "Давление перед наливом 3–4 бар, иногда прыгает до 5–6. "
            "Конвейер контролируем по току двигателя, клинит из-за заклинивших бутылок. "
            "Влажность проблем не создаёт."
        )
    },

    # Orchestrator → enough data → digital_twin_agent(requirements, db_schema)
    {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_dt_design_001",
                "type": "function",
                "function": {
                    "name": "digital_twin_agent",
                    "arguments": {
                        "requirements": "{\"product\": \"лимонад\", \"line_stage\": \"розлив_укупорка\", \"signals\": {\"product_temp\": {\"after_pasteurizer\": \"6-8°C\", \"alarm\": \">12°C\"}, \"filler_pressure\": {\"normal\": \"3-4 бар\", \"spikes\": \"5-6 бар\"}, \"conveyor_drive\": {\"monitoring\": \"motor_current\", \"failure\": \"jamming\"}}, \"environment\": {\"humidity_relevant\": false}, \"constraints\": [\"food_grade\", \"IP67+\"]}",
                        "db_schema": "{\"tables\": [{\"name\": \"sensors\", \"columns\": [\"id\", \"name\", \"location\", \"thresholds\"]}, {\"name\": \"process_params\", \"columns\": [\"key\", \"value\"]}]}"
                    }
                }
            }
        ]
    },

    # digital_twin_agent returns sensor design
    {
        "role": "tool",
        "tool_call_id": "call_dt_design_001", 
        "name": "digital_twin_agent",
        "content": (
            '{"recommended_sensors":['
            '{"name":"PT100_RTD_food","qty":2,"locations":["after_pasteurizer","before_filler"],'
            '"thresholds":{"warn":8,"alarm":12},"notes":"гигиенич.исп.,3A/SS304"},'
            '{"name":"PPT-100_pressure","qty":1,"range":"0-10bar","location":"before_filler",'
            '"thresholds":{"normal":[3,4],"warn":5.5,"alarm":6},"notes":"4-20mA,IP67"},'
            '{"name":"VIBRO-M8_vibration","qty":1,"location":"gearbox","range":"0-50mm/s","notes":"RMS 10-1000Hz"},'
            '{"name":"Encoder_Incremental","qty":1,"location":"drive_shaft","notes":"speed+jamming detection"}'
            '],'
            '"thresholds":{"vibration_warn":25,"vibration_alarm":40},'
            '"excluded":["shop_humidity"],"'
            '"rationale":"Влажность не коррелирует с отказами. Вибрация+энкодер лучше отличает механику от клина бутылок."}'
        )
    },

    # Orchestrator → save to database (database_agent: conversation_id + interview_result)
    {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_db_save_001",
                "type": "function",
                "function": {
                    "name": "database_agent",
                    "arguments": {
                        "conversation_id": "conv_001",
                        "interview_result": "sensor_configuration: recommended_sensors=[PT100_RTD_food x2 (after_pasteurizer, before_filler), PPT-100_pressure 0-10bar, VIBRO-M8_vibration gearbox, Encoder_Incremental drive_shaft]; thresholds: temp_warn=8°C, temp_alarm=12°C, pressure_warn=5.5bar, pressure_alarm=6bar, vibration_warn=25mm/s"
                    }
                }
            }
        ]
    },

    # database_agent confirms save
    {
        "role": "tool", 
        "tool_call_id": "call_db_save_001",
        "name": "database_agent",
        "content": '{"status":"success","saved_as":"sensor_config_conv_001","keys":["sensors","thresholds"]}'
    },

    # Orchestrator → generate final UX response (user_interaction: conversation_id + user_message)
    {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_ui_final_001",
                "type": "function",
                "function": {
                    "name": "user_interaction",
                    "arguments": {
                        "conversation_id": "conv_001",
                        "user_message": "Передать пользователю итог: Конфигурация датчиков для линии розлива сохранена в БД. Нужны: 2×PT100 температура, PPT-100 давление, VIBRO-M8 вибрация, энкодер. Пороги: temp>8°C предупр./>12°C авария, pressure>5.5/6 бар. Влажность цеха исключена. Следующие шаги: CIP/мойки, зоны установки, интеграция с PLC."
                    }
                }
            }
        ]
    },

    # user_interaction → perfect UX response
    {
        "role": "tool",
        "tool_call_id": "call_ui_final_001",
        "name": "user_interaction",
        "content": (
            "✅ **Конфигурация датчиков для линии розлива** (сохранена в БД conv_001):\n\n"
            "**📊 Нужны (4 датчика):**\n"
            "• **Температура продукта**: 2× PT100 (гигиенич.исп.) — после пастеризатора + перед наливом\n"
            "  *⚠️ >8°C предупреждение, 🚨 ≥12°C авария*\n"
            "• **Давление перед наливом**: PPT-100 (0-10 бар)\n"
            "  *⚠️ >5.5 бар предупреждение, 🚨 ≥6 бар авария*\n" 
            "• **Конвейер**: VIBRO-M8 вибрация (редуктор) + энкодер скорости (вал)\n"
            "  *Разделяет клин бутылок от механических проблем*\n\n"
            "**❌ Лишнее**: датчик влажности цеха (не влияет на отказы)\n\n"
            "**🔧 Следующие шаги?**\n"
            "1. CIP/мойки есть? (для выбора материалов)\n"
            "2. Мокрая/сухая зона установки?\n"
            "3. Интеграция с PLC (Modbus/Profibus/EthernetIP)?"
        )
    },

    # Orchestrator → echoes final response to user
    {
        "role": "assistant",
        "content": "✅ **Конфигурация датчиков для линии розлива** (сохранена в БД conv_001):\n\n**📊 Нужны (4 датчика):**\n• **Температура продукта**: 2× PT100 (гигиенич.исп.) — после пастеризатора + перед наливом\n  *⚠️ >8°C предупреждение, 🚨 ≥12°C авария*\n• **Давление перед наливом**: PPT-100 (0-10 бар)\n  *⚠️ >5.5 бар предупреждение, 🚨 ≥6 бар авария*\n• **Конвейер**: VIBRO-M8 вибрация (редуктор) + энкодер скорости (вал)\n  *Разделяет клин бутылок от механических проблем*\n\n**❌ Лишнее**: датчик влажности цеха (не влияет на отказы)\n\n**🔧 Следующие шаги?**\n1. CIP/мойки есть? (для выбора материалов)\n2. Мокрая/сухая зона установки?\n3. Интеграция с PLC (Modbus/Profibus/EthernetIP)?"
    }
]



class OrchestratorAgent(BaseAgent):
    """
    Мета-агент: маршрутизирует высокоуровневые запросы между профильными агентами.
    Использует строгие XML-теги и JSON схемы для управления LLM (Nemotron-Orchestrator-8B).
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
        """
        Собирает состояние в формате ChatML + XML, который ожидает Nemotron-Orchestrator-8B:
        - добавляет описание tools;
        - вшивает few-shot диалог;
        - даёт инструкцию думать в <think> и эмитить JSON tool_call.
        """

        tools_json = json.dumps(ORCHESTRATOR_TOOLS_JSON, ensure_ascii=False, indent=2)

        system_prompt = (
            "You are an expert orchestrator agent managing a factory Digital Twin.\n"
            "You may call one or more functions to assist with the user query.\n\n"
            "You are provided with function signatures within <tools></tools> XML tags:\n"
            "<tools>\n"
            f"{tools_json}\n"
            "</tools>\n\n"
            "For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n"
            "<tool_call>\n"
            "{\"name\": \"<function-name>\", \"arguments\": <args-json-object>}\n"
            "</tool_call>\n\n"
            "Always first think through the problem and plan the sequence of tool calls inside <think>...</think> tags.\n"
            "Then output one or more <tool_call> blocks with strict JSON (no extra text before or after the JSON object inside the tag).\n"
            "If you want to return a final, highly structured action plan, call the \"finish\" tool with a JSON object in the \"result\" field.\n"
        )

        prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n"

        # few-shot диалог
        for m in FEWSHOT_DIALOG:
            role = m["role"]
            content = m["content"]
            prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"

        # История реального диалога
        if messages:
            for m in messages[-10:]:
                role = m.get("role", "user")
                content = m.get("content", "")
                prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"

        # Текущий запрос + сенсоры
        current_context = (
            f"Текущие показания датчиков: "
            f"{json.dumps(sensor_readings, ensure_ascii=False) if sensor_readings else 'Нет данных'}\n"
            f"Запрос пользователя: {task_params.get('request', '') if task_params else ''}"
        )

        prompt += f"<|im_start|>user\n{current_context}<|im_end|>\n<|im_start|>assistant\n"
        return prompt

    def _generate(self, prompt: str) -> str:
        """
        Заглушка для инференса модели.
        Ожидается, что Nemotron-Orchestrator-8B вернет:
        <think>...</think>
        <tool_call>{...}</tool_call>
        [<tool_call>{...}</tool_call> ...]
        """
        # Здесь должен быть реальный вызов LLM:
        # inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        # outputs = self._model.generate(**inputs, max_new_tokens=512)
        # return self._tokenizer.decode(outputs[0][inputs.input_ids.shape[-1]:])

        # Симуляция ответа модели для тестирования пайплайна
        return (
            "<think>Мне нужно записать конфигурацию в БД и затем вернуть automation pipeline.</think>\n"
            "<tool_call>{\"name\": \"database_agent\", \"arguments\": {\"conversation_id\": \"conv_123\", \"interview_result\": \"...\"}}</tool_call>\n"
            "<tool_call>{\"name\": \"finish\", \"arguments\": {\"result\": {\"type\": \"automation_pipeline\", \"steps\": []}}}</tool_call>"
        )

    # --- парсер JSON tool_call из ответа модели ---

    TOOL_CALL_RE = re.compile(
        r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
        re.DOTALL
    )

    def _parse_tool_calls(self, raw_output: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Возвращает:
        - reasoning (строка из <think>...</think>);
        - список tool_call (dict с полями name, arguments).
        """
        think_match = re.search(r"<think>(.*?)</think>", raw_output, re.DOTALL)
        reasoning = think_match.group(1).strip() if think_match else ""

        calls: List[Dict[str, Any]] = []
        for match in self.TOOL_CALL_RE.finditer(raw_output):
            raw_json = match.group(1)
            try:
                data = json.loads(raw_json)
                if isinstance(data, dict) and "name" in data and "arguments" in data:
                    calls.append(data)
            except json.JSONDecodeError:
                self.log(f"Failed to parse tool_call JSON: {raw_json}", "warning")

        return reasoning, calls

    def _execute_tool(self, tool_call: Dict[str, Any], reasoning: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Выполняет один вызов инструмента. Возвращает:
        - result_text для модели (для <tool_response>);
        - metadata для reward (latency, success и т.п.).
        """
        tool_name = tool_call.get("name", "").strip()
        args = tool_call.get("arguments", {})
        metadata = {"tool": tool_name, "latency_ms": 0, "success": False, "reasoning": reasoning}

        t0 = time.perf_counter()
        result = ""

        if tool_name == "finish":
            # Интерпретируем result как строку или JSON.
            result = args.get("result", "Готово.")
            metadata["success"] = True

        elif tool_name == "user_interaction":
            result = "[stub] user_interaction: делегировано агенту взаимодействия"
            metadata["success"] = True

        elif tool_name == "database_agent":
            # При интеграции с реальным агентом: вызвать агента БД с conversation_id и
            # interview_result, получить SQL, затем применить через DatabaseManager.execute(sql).
            result = "[stub] database_agent: схема сгенерирована и применена к БД"
            metadata["success"] = True

        elif tool_name == "digital_twin_agent":
            result = "[stub] digital_twin_agent: конфигурация цифрового двойника сгенерирована"
            metadata["success"] = True

        elif tool_name == "ipcamera_gige":
            result = "[stub] ipcamera_gige: действие выполнено"
            metadata["success"] = True

        elif tool_name == "ipcamera_rtsp":
            result = "[stub] ipcamera_rtsp: действие не выполнено (заглушка)"
            metadata["success"] = False

        elif tool_name == "sensor_manager":
            if self._sensor_manager:
                data = self._sensor_manager.get_data()
                result = json.dumps(data, ensure_ascii=False) if data else "{}"
                metadata["success"] = True
            else:
                result = "Ошибка: SensorManager недоступен"
                metadata["success"] = False
        else:
            result = f"Ошибка: Неизвестный инструмент {tool_name}"

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
        Цикл оркестратора: принимает запрос, генерирует JSON tool_call через CoT,
        выполняет их, кормит результаты обратно в модель, пока не будет вызван 'finish'.
        """
        self._step_count = 0
        self._llm_call_count = 0
        steps: List[Dict[str, Any]] = []
        context = context or {}

        sensor_readings = None
        if self._sensor_manager:
            raw_readings = self._sensor_manager.get_data()
            if raw_readings:
                sensor_readings = raw_readings.get("sensor_data", {})

        # Стартовый промпт
        prompt = self._build_state(
            conversation_id=conversation_id,
            messages=context.get("messages", []),
            sensor_readings=sensor_readings,
            task_params={"request": high_level_request, **context},
        )

        self._load_model()

        final_result = ""
        finished = False

        for _ in range(self.max_tool_steps):
            raw_output = self._generate(prompt)
            self._llm_call_count += 1

            # парсим CoT + tool_call
            reasoning, tool_calls = self._parse_tool_calls(raw_output)

            if not tool_calls:
                steps.append({"tool": "none", "result_preview": raw_output, "reasoning": reasoning})
                break

            # каждый tool_call — отдельный шаг
            for tc in tool_calls:
                tool_name = tc.get("name")
                if tool_name == "finish":
                    # finish не исполняем как внешний API, просто фиксируем результат и выходим
                    final_result = tc.get("arguments", {}).get("result", "")
                    steps.append(
                        {
                            "tool": "finish",
                            "reasoning": reasoning,
                            "result": final_result,
                            "success": True,
                        }
                    )
                    finished = True
                    break

                result_text, meta = self._execute_tool(tc, reasoning, context)
                steps.append({**meta, "result_preview": str(result_text)[:200]})

                # возвращаем результат инструмента в модель в виде <tool_response>
                prompt += f"{raw_output}<|im_end|>\n"
                prompt += f"<|im_start|>user\n<tool_response>\n{result_text}\n</tool_response>\n<|im_end|>\n<|im_start|>assistant\n"

            if finished:
                break

        reward = self.compute_reward(
            steps,
            sensor_sim_vs_real=sensor_readings,
            outcome_success=finished,
        )

        return {
            "result": final_result or (steps[-1].get("result", steps[-1].get("result_preview", "")) if steps else ""),
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
