# SimBench Steel Casting Evaluator v4.0
## Реализация протокола из статьи "SimBench: A Framework for Evaluating and Diagnosing LLM-Based Digital-Twin Generation"

**🧑‍🎓 Опирается на:** Wang J. et al., "SimBench: A Framework for Evaluating and Diagnosing LLM-Based Digital-Twin Generation for Multi-Physics Simulation", IEEE Transactions on Artificial Intelligence, arXiv:2408.11987v2 (2026)

***

### 🎯 **Назначение**
**Полная реализация 3-ходового протокола SimBench (SEN категория)** для оценки S-LLM на задаче цифрового двойника непрерывной разливки стали:

```
Turn 1 (Vague): Нормальный режим → базовая PyChrono модель
Turn 2 (Sharp): Аварийный режим → кодовая модификация  
Turn 3 (Complex): Критический режим → ChSensorManager + аварийная логика
```

**Метрики:** J-LLM-as-a-judge (rubric-based) + Pass@1 + авто-оценка

***

## 📁 **Файловая структура `simbench.py`**

```
.
├── simbench.py                          # 🎮 SimBench evaluator
├── model_inputs/                        # 📥 Входы (PyChrono код)
│   ├── steel_text_v1.txt                # пороговые значения стали
│   ├── sllm_turn1.txt → sllm_turn3.txt  # S-LLM коды (3 хода)
│   └── baseline_turn1.txt → turn3.txt   # baseline коды (3 хода)
└── llm_judge/                           # 🤖 J-LLM зона  
    ├── llm_judge_input/                 # auto-generated JSON → в J-LLM
    └── judge_results/                   # ← ВЫ кладёте 6 JSON вердиктов
```

***

## 🚀 **SimBench WORKFLOW (по статье)**

### **1. Генерация input-ов J-LLM**
```bash
python simbench.py
```
**Создаёт:** `llm_judge/llm_judge_input/jllm_input_turn[1-3]_vX.json`

### **2. Прогон J-LLM (SimBench J-LLM-as-a-judge)**
**Копируете JSON → Claude-4 / GPT-4o → сохраняете вердикты**

**Формат вердикта** (SimBench rubric [[score]]):
```json
{
  "turn": 1, "model": "sllm", 
  "score": 82.5,
  "verdict": "[[82.5]] Completeness 38/40, Correctness 25/30..."
}
```

### **3. Финальная оценка**
```
Нажать Enter → автоматическая таблица SimBench:
   Turn | S-LLM_auto | S-LLM_JLLM | Base_JLLM | Pass@1
    1   |    85     |   82.5     |   71.0    |  ✅❌
```

***

## 📊 **SimBench метрики (по статье)**

| Метрика | Вес | Критерии |
|---------|-----|----------|
| Completeness | 40 | PyChrono структура, сенсоры |
| Correctness | 30 | Сталелитейные пороги |
| Sensors | 15 | ChSensorManager, LiDAR |
| Sim Loop | 10 | DoStepDynamics |
| Viz | 5 | Irrlicht/ChVisualSystem |

**Выход:** `final_results_v1.csv`

***

## ⚙️ **Версионирование (SimBench dataset evolution)**

```
steel_text_v1.txt → v2.txt → v3.txt (берётся максимальная версия)
jllm_input_turn1_v3.json
final_results_v3.csv
```

***

## 📝 **Пример steel_text_v1.txt**
```
Пороговые значения: температура 1510–1550°C (норма), <1490/>1570°C (кризис)...
```

***

## 🛠 **README команда**
```bash
mkdir -p model_inputs llm_judge/{llm_judge_input,judge_results}
echo "Пороговые значения..." > model_inputs/steel_text_v1.txt
# ... коды моделей в *_turn*.txt
python simbench.py  # → ждёт J-LLM вердикты
```

**🎓 100% SimBench протокол**: multi-turn → J-LLM judge → Pass@k!**

***