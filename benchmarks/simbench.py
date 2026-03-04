#!/usr/bin/env python3
"""
SimBench Steel Casting Evaluator v4.1
Реализация протокола SimBench SEN (Wang et al., arXiv:2408.11987v2) для оценки 
цифровых двойников непрерывной разливки стали с progressive complexity.
"""

import os
import re
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Tuple
import pandas as pd

@dataclass
class EvaluationResult:
    auto_score: float
    jllm_score: float
    feedback: str
    pass_success: bool
    compile_success: bool

class SimBenchSteelCastingEvaluator:
    def __init__(self, inputs_dir: str = "model_inputs", judge_dir: str = "llm_judge"):
        self.inputs_dir = Path(inputs_dir)
        self.judge_dir = Path(judge_dir)
        self.judge_input_dir = self.judge_dir / "llm_judge_input"
        self.judge_results_dir = self.judge_dir / "judge_results"

    def create_simbench_prompts(self, steel_text: str) -> List[str]:
        """SimBench SEN промпты с progressive complexity (строго по статье)"""
        return [
            # Turn 1: VAGUE - базовая генерация
            f"""PyChrono эксперт. Создай цифровой двойник непрерывной разливки стали в НОРМАЛЬНОМ режиме:

{steel_text}

Параметры:
• Температура стали: 1520°C (норма 1510–1550°C)  
• Скорость разливки: 1.4 м/мин (норма 1.3–1.5 м/мин)
• Расход воды охлаждения: 1200 м³/ч (норма 960–1440 м³/ч)
• Вибрация оборудования: 4.0 мм/с RMS (норма)

Требования:
1. PyChrono ChSystemNSC
2. Модель кристаллизатора (цилиндр/труба)
3. Базовые сенсоры (LiDAR/camera)
4. Irrlicht визуализация
5. Симуляционный цикл

ВЫВЕДИ ТОЛЬКО ИСПОЛНЯЕМЫЙ PYTHON КОД БЕЗ КОММЕНТАРИЕВ.""",

            # Turn 2: SHARP - модификация Turn 1 кода
            f"""МОДИФИЦИРУЙ КОД ИЗ Turn 1 для АВАРИЙНОГО РЕЖИМА:

{steel_text}

Изменения:
1. Температура стали: 1510°C (нижний АВАРИЙНЫЙ порог)
2. Скорость разливки: 1.2 м/мин (АВАРИЙНАЯ <1.2 м/мин)  
3. Расход воды: 1440 м³/ч (верхний АВАРИЙНЫЙ предел)
4. Вибрация: 5.2 мм/с RMS (АВАРИЙНАЯ 5.2–6.0 мм/с)

Дополнительно:
5. Добавить предупредительные индикаторы (print/warnings)
6. Изменить визуализацию (красный цвет для аварии)

ВЫВЕДИ ТОЛЬКО ОБНОВЛЁННЫЙ ИСПОЛНЯЕМЫЙ PYTHON КОД.""",

            # Turn 3: COMPLEX - расширение Turn 2 + продвинутые сенсоры
            f"""РАСШИРЬ КОД ИЗ Turn 2 для КРИТИЧЕСКОГО РЕЖИМА + продвинутые сенсоры:

{steel_text}

Критические параметры:
1. Температура: 1485°C (КРИТИЧЕСКАЯ <1490°C)
2. Расход воды: 830 м³/ч (КРИТИЧЕСКИЙ <840 м³/ч)
3. Вибрация: 6.2 мм/с RMS (КРИТИЧЕСКАЯ >6.0 мм/с)

Технические требования:
4. pychrono.sensor.ChSensorManager
5. High-res LiDAR: 1024x64 samples, 360° HFoV, 50m range  
6. RGB Camera: 90° FoV, front mount
7. Логика АВАРИЙНОЙ ОСТАНОВКИ при любом критич. параметре
8. PointCloud визуализация (800x600)

ВЫВЕДИ ТОЛЬКО ФИНАЛЬНЫЙ ИСПОЛНЯЕМЫЙ PYTHON КОД."""
        ]

    def step1_generate_jllm_inputs(self) -> Tuple[str, List[str], List[str], List[str]]:
        """ШАГ 1: Генерация SimBench input-ов для J-LLM"""
        print("🚀 ШАГ 1: SimBench SEN - генерация J-LLM input-ов")
        
        # Загрузка steel_text
        steel_text, version = self.load_latest_steel_text()
        prompts = self.create_simbench_prompts(steel_text)
        
        # Загрузка кодов
        sllm_codes, baseline_codes = self.load_model_outputs()
        
        # Создание JSON-ов
        self.judge_input_dir.mkdir(parents=True, exist_ok=True)
        
        for i, (prompt, s_code, b_code) in enumerate(zip(prompts, sllm_codes, baseline_codes), 1):
            jllm_input = {
                "turn": i,
                "turn_type": ["VAGUE", "SHARP", "COMPLEX"][i-1],
                "steel_version": version,
                "steel_text": steel_text,
                "simbench_prompt": prompt,
                "sllm_code": s_code,
                "baseline_code": b_code,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            
            input_file = self.judge_input_dir / f"simbench_input_turn{i}_{version}.json"
            input_file.write_text(json.dumps(jllm_input, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"   💾 simbench_input_turn{i}_{version}.json (Turn {i} {'VAGUE,SHARP,COMPLEX'.split(',')[i-1]})")
        
        print(f"\n✅ Создано 3 SimBench JSON в {self.judge_input_dir}")
        return steel_text, prompts, sllm_codes, baseline_codes

    def load_latest_steel_text(self) -> Tuple[str, str]:
        """Загрузка последней версии steel_text_vX.txt"""
        steel_files = list(self.inputs_dir.glob("steel_text_v*.txt"))
        if not steel_files:
            raise FileNotFoundError(f"❌ Не найдены steel_text_v*.txt в {self.inputs_dir}")
        
        def extract_version(f): 
            return int(re.search(r'v(\d+)', f.name).group(1))
        
        latest = max(steel_files, key=extract_version)
        version = re.search(r'v(\d+)', latest.name).group(1)
        steel_text = latest.read_text(encoding="utf-8").strip()
        
        print(f"✅ Загружен steel_text_v{version}.txt ({len(steel_text)} символов)")
        return steel_text, f"v{version}"

    def load_model_outputs(self) -> Tuple[List[str], List[str]]:
        """Загрузка sllm_turn*.txt и baseline_turn*.txt"""
        sllm_files = sorted(self.inputs_dir.glob("sllm_turn*.txt"))
        baseline_files = sorted(self.inputs_dir.glob("baseline_turn*.txt"))
        
        if len(sllm_files) != 3 or len(baseline_files) != 3:
            print(f"❌ Нужны по 3 файла. Найдено: S-LLM={len(sllm_files)}, Baseline={len(baseline_files)}")
            return [], []
        
        sllm_codes = [f.read_text(encoding="utf-8").strip() for f in sllm_files]
        baseline_codes = [f.read_text(encoding="utf-8").strip() for f in baseline_files]
        
        print(f"✅ Загружено: S-LLM={len(sllm_codes)} ходов, Baseline={len(baseline_codes)} ходов")
        return sllm_codes, baseline_codes

    def step2_wait_jllm_results(self, poll_interval: int = 10, timeout: int = 3600) -> Dict:
        """ШАГ 2: Ожидание 6 вердиктов J-LLM"""
        print(f"\n⏳ ШАГ 2: Ожидание J-LLM вердиктов...")
        print(f"📁 Кладите в: {self.judge_results_dir}/judge_results_*.json")
        print("   Нужны 6 файлов: sllm_turn[1-3] + baseline_turn[1-3]")
        
        self.judge_results_dir.mkdir(parents=True, exist_ok=True)
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            results = list(self.judge_results_dir.glob("judge_results_*.json"))
            if len(results) >= 6:
                print(f"\n✅ Найдено {len(results)}/6 вердиктов!")
                break
            print(f"⏳ Ожидание... ({len(results)}/6)", end='\r')
            time.sleep(poll_interval)
        
        # Парсинг
        verdicts = {}
        for result_file in results:
            try:
                data = json.loads(result_file.read_text(encoding="utf-8"))
                turn = data.get("turn")
                model = data.get("model")
                key = f"{model}_turn{turn}"
                
                score_match = re.search(r'\[\[(\d+(?:\.\d+)?)\]\]', data.get("verdict", ""))
                score = float(score_match.group(1)) if score_match else data.get("score", 0.0)
                
                verdicts[key] = {
                    "file": result_file.name,
                    "score": score,
                    "feedback": data.get("feedback", ""),
                    "model": model,
                    "turn": turn
                }
                print(f"   ✅ {result_file.name}: {score:.1f}")
            except Exception as e:
                print(f"⚠️  {result_file.name}: {e}")
        
        return verdicts

    def rubric_auto_score(self, code: str, turn: int) -> EvaluationResult:
        """Автоматическая оценка (fallback)"""
        score = 100.0
        feedback = []
        
        # Completeness (40)
        if "pychrono" not in code.lower(): 
            feedback.append("-20: нет PyChrono"); score -= 20
        if "ChSystem" not in code: 
            feedback.append("-15: нет ChSystem"); score -= 15
        
        # Turn-specific (30)
        if turn == 1 and "1520" not in code: score -= 10
        elif turn == 2 and "1510" not in code: score -= 10  
        elif turn == 3 and "1485" not in code: score -= 10
        
        # Sensors (15) - прогрессивно
        sensor_pts = sum(1 for x in ["ChSensorManager", "ChLidarSensor"] if x in code)
        score += sensor_pts * 7
        
        # Sim loop + viz (15)
        if "DoStepDynamics" not in code and "while" not in code: 
            feedback.append("-10: нет симуляции"); score -= 10
        if "irrlicht" not in code.lower(): 
            feedback.append("-5: нет визуализации"); score -= 5
            
        score = max(0, min(100, score))
        return EvaluationResult(
            auto_score=score, jllm_score=0, feedback="; ".join(feedback),
            pass_success=score >= 75, compile_success="ChSystem" in code
        )

    def step3_final_evaluation(self, prompts: List[str], sllm_codes: List[str], 
                             baseline_codes: List[str], jllm_verdicts: Dict) -> pd.DataFrame:
        """ШАГ 3: Финальная SimBench таблица"""
        print("\n🚀 ШАГ 3: SimBench SEN финальная оценка")
        
        results = []
        turn_types = ["VAGUE", "SHARP", "COMPLEX"]
        
        for i in range(3):
            turn = i + 1
            s_code, b_code = sllm_codes[i], baseline_codes[i]
            
            # Auto score
            s_auto = self.rubric_auto_score(s_code, turn)
            b_auto = self.rubric_auto_score(b_code, turn)
            
            # J-LLM score
            s_jllm = jllm_verdicts.get(f"sllm_turn{turn}", {})
            b_jllm = jllm_verdicts.get(f"baseline_turn{turn}", {})
            
            results.append({
                'Turn': turn,
                'Type': turn_types[i],
                'S-LLM_auto': f"{s_auto.auto_score:.0f}",
                'S-LLM_JLLM': f"{s_jllm.get('score', 0):.0f}",
                'Base_auto': f"{b_auto.auto_score:.0f}",
                'Base_JLLM': f"{b_jllm.get('score', 0):.0f}",
                'S-LLM_Pass@1': '✅' if s_auto.pass_success else '❌',
                'Base_Pass@1': '✅' if b_auto.pass_success else '❌',
                'Winner': 'S-LLM' if s_jllm.get('score', 0) > b_jllm.get('score', 0) else 'Base'
            })
            
            print(f"Turn {turn} ({turn_types[i]}): "
                  f"S-LLM {s_auto.auto_score:.0f}/{s_jllm.get('score', '-'):.0f} | "
                  f"Base {b_auto.auto_score:.0f}/{b_jllm.get('score', '-'):.0f}")
        
        df = pd.DataFrame(results)
        return df

def main():
    print("🔥 SimBench Steel Casting Evaluator v4.1")
    print("Реализация Wang et al., arXiv:2408.11987v2 (SEN протокол)")
    print("=" * 70)
    
    evaluator = SimBenchSteelCastingEvaluator()
    
    # ШАГ 1: Генерация SimBench JSON-ов
    steel_text, prompts, sllm_codes, baseline_codes = evaluator.step1_generate_jllm_inputs()
    
    print("\n🎯 ВАШИ ДЕЙСТВИЯ (SimBench J-LLM-as-a-judge):")
    print("1. 📋 Скопируйте 3 JSON из llm_judge/llm_judge_input/")
    print("2. 🤖 Прогоняете через Claude-4/GPT-4o/Sonnet")
    print("3. 💾 Создаёте 6 вердиктов в llm_judge/judge_results/")
    print("   Формат: {'turn':1, 'model':'sllm', 'score':85.0, 'verdict':'[[85.0]]...'}\n")
    
    input("\n⌨️  Нажмите Enter ПОСЛЕ создания ВСЕХ 6 judge_results_*.json...")
    
    # ШАГ 2: Чтение J-LLM вердиктов
    jllm_verdicts = evaluator.step2_wait_jllm_results()
    
    # ШАГ 3: Финальная таблица
    df = evaluator.step3_final_evaluation(prompts, sllm_codes, baseline_codes, jllm_verdicts)
    
    print("\n🏆 SIMBENCH SEN РЕЗУЛЬТАТЫ:")
    print(df.to_string(index=False))
    
    # Pass@k и статистика
    sllm_passk = df['S-LLM_Pass@1'].eq('✅').sum()
    base_passk = df['Base_Pass@1'].eq('✅').sum()
    sllm_avg_jllm = pd.to_numeric(df['S-LLM_JLLM'].str[:-1]).mean()
    
    print(f"\n📊 Pass@k (k=1): S-LLM={sllm_passk}/3 | Baseline={base_passk}/3")
    print(f"🏅 Средний J-LLM score: S-LLM={sllm_avg_jllm:.1f}")
    
    # Сохранение
    version = evaluator.load_latest_steel_text()[1]
    df.to_csv(f"simbench_results_{version}.csv", index=False)
    print(f"\n💾 simbench_results_{version}.csv")
    
    print("\n🎓 SimBench SEN протокол завершён!")

if __name__ == "__main__":
    main()
