#!/usr/bin/env python3
"""
Steel Casting SimBench Evaluator v4.0 - Асинхронный J-LLM workflow
1. Генерирует input-ы для J-LLM → llm_judge_input/
2. ЖДЕТ пока вы вручную запишете вердикты → llm_judge/judge_results_*.json
3. Автоматически собирает финальную таблицу
"""

import os
import re
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Any
import pandas as pd

@dataclass
class EvaluationResult:
    auto_score: float
    jllm_score: float
    feedback: str
    pass_success: bool

class SteelCastingEvaluator:
    def __init__(self, inputs_dir: str = "model_inputs", judge_dir: str = "llm_judge"):
        self.inputs_dir = Path(inputs_dir)
        self.judge_dir = Path(judge_dir)
        self.judge_input_dir = self.judge_dir / "llm_judge_input"
        self.judge_results_dir = self.judge_dir / "judge_results"

    def step1_generate_jllm_inputs(self) -> tuple[str, List[str]]:
        """ШАГ 1: Генерирует input-ы для J-LLM"""
        print("🚀 ШАГ 1: Генерация входов для J-LLM")
        
        # Загрузка steel_text
        steel_text, version = self.load_latest_steel_text()
        prompts = self.create_prompts(steel_text)
        
        # Загрузка кодов моделей
        sllm_codes, baseline_codes = self.load_model_outputs()
        
        # Создание папки и JSON-ов
        self.judge_input_dir.mkdir(parents=True, exist_ok=True)
        inputs_created = []
        
        for i, (prompt, s_code, b_code) in enumerate(zip(prompts, sllm_codes, baseline_codes), 1):
            jllm_input = {
                "turn": i,
                "steel_version": version,
                "steel_text": steel_text,
                "task_prompt": prompt,
                "sllm_code": s_code,
                "baseline_code": b_code,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            
            input_file = self.judge_input_dir / f"jllm_input_turn{i}_v{version}.json"
            input_file.write_text(json.dumps(jllm_input, ensure_ascii=False, indent=2), encoding="utf-8")
            inputs_created.append(str(input_file))
            print(f"   💾 {input_file.name}")
        
        print(f"\n✅ Готово! {len(inputs_created)} файлов в {self.judge_input_dir}")
        print("📋 Далее: скопируйте JSON-ы в J-LLM и получите вердикты!")
        return steel_text, prompts

    def step2_wait_jllm_results(self, poll_interval: int = 5, timeout: int = 3600) -> Dict:
        """ШАГ 2: ЖДЕТ результаты J-LLM в judge_results/"""
        print(f"\n⏳ ШАГ 2: Ожидание результатов J-LLM...")
        print(f"📁 Поместите вердикты в: {self.judge_results_dir}/judge_results_*.json")
        print(f"⏱️  Проверка каждые {poll_interval}с (таймаут {timeout//60}мин)")
        
        self.judge_results_dir.mkdir(parents=True, exist_ok=True)
        
        start_time = time.time()
        expected_count = 6  # 3 S-LLM + 3 Baseline
        
        while time.time() - start_time < timeout:
            result_files = list(self.judge_results_dir.glob("judge_results_*.json"))
            
            if len(result_files) >= expected_count:
                print(f"\n✅ Найдено {len(result_files)} вердиктов J-LLM!")
                break
                
            print(f"⏳ Ожидание... ({len(result_files)}/{expected_count})", end='\r')
            time.sleep(poll_interval)
        
        if len(result_files) < expected_count:
            print(f"\n⚠️  Найдено только {len(result_files)}/{expected_count} вердиктов")
        
        # Парсинг вердиктов
        verdicts = {}
        for result_file in result_files:
            try:
                data = json.loads(result_file.read_text(encoding="utf-8"))
                turn = data.get("turn")
                model = data.get("model")  # "sllm" или "baseline"
                key = f"{model}_turn{turn}"
                
                # Извлекаем [[score]] или json.score
                score_match = re.search(r'\[\[(\d+(?:\.\d+)?)\]\]', data.get("verdict", ""))
                score = float(score_match.group(1)) if score_match else data.get("score", 0.0)
                
                verdicts[key] = {
                    "file": result_file.name,
                    "score": score,
                    "feedback": data.get("feedback", data.get("verdict", "")),
                    "model": model,
                    "turn": turn
                }
            except Exception as e:
                print(f"⚠️ Ошибка парсинга {result_file}: {e}")
        
        return verdicts

    def step3_final_evaluation(self, steel_text: str, prompts: List[str], 
                              sllm_codes: List[str], baseline_codes: List[str], 
                              jllm_verdicts: Dict) -> pd.DataFrame:
        """ШАГ 3: Финальная таблица"""
        print("\n🚀 ШАГ 3: Финальная оценка")
        
        results = []
        for i in range(1, 4):  # 3 хода
            s_code, b_code = sllm_codes[i-1], baseline_codes[i-1]
            
            # Авто-оценка
            s_auto = self.rubric_score(s_code, i)
            b_auto = self.rubric_score(b_code, i)
            
            # J-LLM оценка
            s_jllm = jllm_verdicts.get(f"sllm_turn{i}", {})
            b_jllm = jllm_verdicts.get(f"baseline_turn{i}", {})
            
            results.append({
                'Turn': i,
                'S-LLM_auto': f"{s_auto.auto_score:.0f}",
                'S-LLM_JLLM': f"{s_jllm.get('score', 0):.0f}",
                'Base_auto': f"{b_auto.auto_score:.0f}",
                'Base_JLLM': f"{b_jllm.get('score', 0):.0f}",
                'S-LLM_Pass': '✅' if s_auto.pass_success else '❌',
                'Base_Pass': '✅' if b_auto.pass_success else '❌'
            })
            
            print(f"Turn {i}: S-LLM {s_auto.auto_score:.0f}/{s_jllm.get('score', '-'):.0f} | "
                  f"Base {b_auto.auto_score:.0f}/{b_jllm.get('score', '-'):.0f}")
        
        return pd.DataFrame(results)

    # ---------- Вспомогательные методы ----------
    def load_latest_steel_text(self) -> tuple[str, str]:
        steel_files = list(self.inputs_dir.glob("steel_text_v*.txt"))
        latest = max(steel_files, key=lambda f: int(re.search(r'v(\d+)', f.name).group(1)))
        version = re.search(r'v(\d+)', latest.name).group(1)
        return latest.read_text(encoding="utf-8").strip(), f"v{version}"

    def load_model_outputs(self) -> tuple[List[str], List[str]]:
        sllm_files = sorted(self.inputs_dir.glob("sllm_turn*.txt"))
        baseline_files = sorted(self.inputs_dir.glob("baseline_turn*.txt"))
        return ([f.read_text(encoding="utf-8").strip() for f in sllm_files],
                [f.read_text(encoding="utf-8").strip() for f in baseline_files])

    def rubric_score(self, code: str, turn: int) -> EvaluationResult:
        """Fallback авто-оценка"""
        score = 100.0
        # упрощенная логика (как раньше)
        if 'ChSystem' not in code: score -= 30
        if 'pychrono' not in code.lower(): score -= 20
        return EvaluationResult(auto_score=score, jllm_score=0, feedback="", pass_success=score>70)

    def create_prompts(self, steel_text: str) -> List[str]:
        return [f"Разливка стали Turn {i}:\n{steel_text}" for i in range(1, 4)]

def main():
    evaluator = SteelCastingEvaluator()
    
    print("🔥 Steel Casting SimBench Evaluator v4.0")
    print("=" * 70)
    
    # ШАГ 1
    steel_text, prompts = evaluator.step1_generate_jllm_inputs()
    sllm_codes, baseline_codes = evaluator.load_model_outputs()
    
    print("\n🎯 ВАШИ ДЕЙСТВИЯ:")
    print("1. Скопируйте JSON из llm_judge_input/")
    print("2. Прогоняете через J-LLM (Claude, GPT-4, etc)")
    print("3. Сохраняете вердикты в llm_judge/judge_results/")
    print("   Формат JSON: {{'turn':1, 'model':'sllm', 'score':85, 'verdict':'...'}}\n")
    
    # ШАГ 2 - БЕСКОНЕЧНОЕ ОЖИДАНИЕ
    input("Нажмите Enter после создания ВСЕХ judge_results_*.json...")
    
    # ШАГ 3  
    jllm_verdicts = evaluator.step2_wait_jllm_results()
    df = evaluator.step3_final_evaluation(steel_text, prompts, sllm_codes, baseline_codes, jllm_verdicts)
    
    print("\n🏆 ФИНАЛЬНАЯ ТАБЛИЦА:")
    print(df.to_string(index=False))
    
    version = evaluator.load_latest_steel_text()[1]
    df.to_csv(f"final_results_{version}.csv", index=False)
    print(f"\n💾 final_results_{version}.csv")

if __name__ == "__main__":
    main()
