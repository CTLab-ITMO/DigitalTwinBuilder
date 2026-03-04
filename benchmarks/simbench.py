#!/usr/bin/env python3
"""
Steel Casting SimBench SEN Evaluator - Версионированный steel_text_v*.txt
Автоматически выбирает последнюю версию steel_text_vX.txt из model_inputs/
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List
import pandas as pd
import glob

@dataclass
class EvaluationResult:
    score: float
    feedback: str
    compile_success: bool
    pass_success: bool
    codebleu: float

class SteelCastingEvaluator:
    def __init__(self, inputs_dir: str = "model_inputs"):
        self.inputs_dir = Path(inputs_dir)

    def load_latest_steel_text(self) -> tuple[str, str]:
        """Находит и загружает последнюю версию steel_text_vX.txt"""
        steel_files = list(self.inputs_dir.glob("steel_text_v*.txt"))
        if not steel_files:
            raise FileNotFoundError(
                f"❌ Не найдены файлы steel_text_v*.txt в {self.inputs_dir}\n"
                f"Создайте хотя бы один: steel_text_v1.txt"
            )
        
        # Сортируем по номеру версии (v1, v2, v10 -> v10 последняя)
        def extract_version(filename):
            match = re.search(r'steel_text_v(\d+)', filename.name)
            return int(match.group(1)) if match else 0
        
        latest_file = max(steel_files, key=extract_version)
        version = extract_version(latest_file)
        
        steel_text = latest_file.read_text(encoding="utf-8").strip()
        
        print(f"✅ Загружен steel_text_v{version}.txt (последняя версия)")
        print(f"📄 Размер: {len(steel_text)} символов")
        
        return steel_text, f"v{version}"

    def load_model_outputs(self) -> tuple[List[str], List[str]]:
        """Читает sllm_turn*.txt и baseline_turn*.txt"""
        if not self.inputs_dir.exists():
            raise FileNotFoundError(f"Папка {self.inputs_dir} не существует!")

        sllm_files = sorted(self.inputs_dir.glob("sllm_turn*.txt"))
        baseline_files = sorted(self.inputs_dir.glob("baseline_turn*.txt"))

        if len(sllm_files) != 3 or len(baseline_files) != 3:
            print(f"❌ Ожидается по 3 файла на модель:")
            print(f"  Найдено S-LLM: {len(sllm_files)}")
            print(f"  Найдено Baseline: {len(baseline_files)}")
            print("  Нужны: *_turn1.txt, *_turn2.txt, *_turn3.txt")
            return [], []

        sllm_codes = [f.read_text(encoding="utf-8").strip() for f in sllm_files]
        baseline_codes = [f.read_text(encoding="utf-8").strip() for f in baseline_files]

        print(f"✅ Модели загружены:")
        print(f"   S-LLM: {len(sllm_codes)} ходов")
        print(f"   Baseline: {len(baseline_codes)} ходов")
        
        return sllm_codes, baseline_codes

    def parse_params_from_code(self, code: str) -> Dict:
        """Парсит параметры из кода"""
        params = {}
        
        # Температура 14xx-15xx
        temp_match = re.search(r'1[4-5]\d{2}', code)
        if temp_match: params['temp'] = float(temp_match.group())
        
        # Скорость 1.x
        speed_match = re.search(r'1\.[\d\.]+\b', code)
        if speed_match: params['speed'] = float(speed_match.group())
        
        # Расход воды 3-4 цифры
        flow_match = re.search(r'\b(?:[89]\d{2,3}|[12]\d{3})\b', code)
        if flow_match: params['flow'] = float(flow_match.group())
        
        # Вибрация 4-7.x
        vib_match = re.search(r'\b[4-7](?:\.\d+)?\b', code)
        if vib_match: params['vibration'] = float(vib_match.group())
        
        return params

    def rubric_score(self, code: str, turn: int, steel_text: str) -> EvaluationResult:
        """SimBench rubric scoring"""
        feedback = []
        score = 100.0
        
        params = self.parse_params_from_code(code)
        
        # Completeness 40pts
        has_chrono = any(x in code.lower() for x in ['pychrono', 'chrono'])
        if not has_chrono:
            feedback.append("-20: нет PyChrono")
            score -= 20
        if 'ChSystem' not in code:
            feedback.append("-15: нет ChSystem")
            score -= 15
        
        # Correctness 30pts - зависит от хода
        if turn == 1:  # Норма
            if 'temp' in params and not (1510 <= params['temp'] <= 1550):
                feedback.append(f"-10: T={params['temp']}°C ≠ 1510-1550")
                score -= 10
        elif turn == 2:  # Авария
            if 'temp' in params and params['temp'] > 1510:
                feedback.append("-10: для аварии T≤1510°C")
                score -= 10
        elif turn == 3:  # Кризис
            if 'temp' not in params or params['temp'] >= 1490:
                feedback.append("-10: кризис T<1490°C")
                score -= 10
        
        # Sensors 15pts
        sensor_pts = sum(1 for x in ['ChSensorManager', 'ChLidarSensor', 'ChCameraSensor'] if x in code)
        score += sensor_pts * 5
        
        # Sim loop 10pts
        if 'DoStepDynamics' not in code and 'while' not in code:
            feedback.append("-10: нет симуляции")
            score -= 10
        
        # Viz 5pts
        if any(x in code for x in ['irrlicht', 'ChVisualSystem']):
            score += 5
        else:
            feedback.append("-5: нет визуализации")
        
        score = max(0, min(100, score))
        
        return EvaluationResult(
            score=score,
            feedback="; ".join(feedback),
            compile_success=has_chrono and 'DoStepDynamics' in code,
            pass_success=score >= 75,
            codebleu=0.65  # заглушка
        )

def create_prompts(steel_text: str) -> List[str]:
    """3 промпта SimBench SEN"""
    return [
        f"""PyChrono эксперт. Нормальный режим разливки стали:
{steel_text}

1520°C, 1.4м/мин, 1200м³/ч, вибрация 4.0мм/с. Только код.""",
        
        f"""Аварийный режим по порогам:
{steel_text}

1510°C, 1.2м/мин, 1440м³/ч, вибрация 5.2мм/с. Только код.""",
        
        f"""Критический режим + ChSensorManager:
{steel_text}

1485°C, 830м³/ч, вибрация 6.2мм/с. Только код."""
    ]

def main():
    print("🔥 Steel Casting Evaluator v2.0 (версионированный)")
    print("=" * 60)
    
    eval_ = SteelCastingEvaluator()
    
    # Загрузка последней версии steel_text
    steel_text, version = eval_.load_latest_steel_text()
    prompts = create_prompts(steel_text)
    
    # Загрузка моделей
    sllm_codes, baseline_codes = eval_.load_model_outputs()
    
    results = []
    
    for i, (prompt, s_code, b_code) in enumerate(zip(prompts, sllm_codes, baseline_codes), 1):
        print(f"\n🔄 Ход {i}")
        print(f"📝 v{version}: {prompt[:70]}...")
        
        s_res = eval_.rubric_score(s_code, i, steel_text)
        b_res = eval_.rubric_score(b_code, i, steel_text)
        
        results.append({
            'Turn': i,
            'Steel_v': version,
            'S-LLM': f"{s_res.score:.0f}",
            'Pass1': '✅' if s_res.pass_success else '❌',
            'Baseline': f"{b_res.score:.0f}",
            'Pass1_B': '✅' if b_res.pass_success else '❌',
            'Winner': 'S-LLM' if s_res.score > b_res.score else 'Base'
        })
        
        print(f"  S-LLM: {s_res.score:.0f} {'' if s_res.pass_success else '❌'}")
        print(f"  Base:  {b_res.score:.0f} {'' if b_res.pass_success else '❌'}")
    
    df = pd.DataFrame(results)
    print(f"\n📊 РЕЗУЛЬТАТЫ (steel_text_{version})")
    print(df.to_string(index=False))
    
    sllm_avg = pd.to_numeric(df['S-LLM'].str[:-1], errors='coerce').mean()
    print(f"\n🏆 S-LLM: {sllm_avg:.1f}/100")
    
    df.to_csv(f"results_v{version}.csv", index=False)
    print(f"💾 results_v{version}.csv")

if __name__ == "__main__":
    main()
