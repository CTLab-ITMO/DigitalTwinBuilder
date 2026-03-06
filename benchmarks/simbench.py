#!/usr/bin/env python3
"""
SimBench Steel Casting Evaluator v4.4 - Pointwise + Pairwise J-LLM
6 pointwise inputs (sllm1-3, baseline1-3) + 3 pairwise inputs (sllm vs baseline per turn)
"""

import os
import re
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Tuple
import pandas as pd


# ✅ POINTWISE ПРОМПТ (оценка одного кода)
POINTWISE_JUDGE_PROMPT = """You are an expert in digital twin development for industrial production systems, tasked with evaluating a SINGLE generated digital twin implementation. 

Here is the digital twin code to evaluate:
[CODE TO EVALUATE]
{generated_code}
[END OF CODE]

PyChrono API documentation:
{pychrono_api_documentation}

Task specification:
[Task Specification]
{task_description}
[End of Task Specification]

EVALUATION CRITERIA (100 points total):
1. Completeness (40): missing components -15 each
2. Correctness (30): wrong API usage -15 each  
3. Code Quality (10): poor structure -5-10
4. Efficiency (10): redundant code -5 each
5. Error Handling (5): no try/except -5
6. Visualization (5): wrong Irrlicht -3-5

RULES:
- Compare ONLY to task requirements and PyChrono API
- Ignore code length/position bias
- Be objective and consistent

OUTPUT FORMAT (MANDATORY):
1. Brief explanation of deductions
2. Final score: [[X]] where X=0-100.0

EXAMPLE:
Missing ChSystem: -15
Wrong sensor setup: -10
[[75.0]]"""

# ✅ PAIRWISE ПРОМПТ (сравнение sllm vs baseline)
PAIRWISE_JUDGE_PROMPT = """You are an expert judge comparing TWO digital twin implementations for the SAME task.

S-LLM CODE:
[SL-LM]
{sllm_code}
[END S-LLM]

BASELINE CODE (REFERENCE):  
[BASELINE]
{baseline_code}
[END BASELINE]

PyChrono API:
{pychrono_api_documentation}

Task:
[Task Specification]
{task_description}
[End Task]

COMPARE AND RANK:
1. Which code better implements the physical simulation?
2. Which has better sensor integration?  
3. Which follows task requirements closer?
4. Which has higher code quality?

WINNER DETERMINATION:
- Score S-LLM relative to Baseline (0-100%)
- 100 = S-LLM clearly better
- 50 = equal quality
- 0 = Baseline clearly better

OUTPUT FORMAT (MANDATORY):
Explanation which is better and why
Final relative score: [[X]] where X=0-100 (S-LLM vs Baseline)

EXAMPLE:
S-LLM missing sensors (-20), baseline complete
S-LLM poor structure (-10)
[[35.0]]"""


@dataclass
class EvaluationResult:
    auto_score: float
    pointwise_score: float  
    pairwise_score: float
    feedback: str
    pass_success: bool


class SimBenchSteelCastingEvaluator:
    def __init__(self, judge_dir: str = "llm_judge"):
        self.judge_dir = Path(judge_dir)
        self.judge_input_dir = self.judge_dir / "llm_judge_input"
        self.judge_results_dir = self.judge_dir / "judge_results"
        self.pychrono_api_docs = """PyChrono::ChSystemNSC(), AddBody(), AddLink(), ChLidarSensor, DoStepDynamics(), chrono_irrlicht"""

    def step1_generate_all_inputs(self) -> Tuple[List[str], List[str], List[str], List[str]]:
        """ШАГ 1: 6 POINTWISE + 3 PAIRWISE = 9 инпутов для J-LLM"""
        print("🚀 ШАГ 1: Генерация 9 J-LLM inputs (6 pointwise + 3 pairwise)")
        
        json_files = sorted(self.judge_input_dir.glob("simbench_input_turn*.json"))
        if len(json_files) != 3:
            raise FileNotFoundError(f"Нужны 3 simbench_input_turn*.json")
        
        data_list = [json.loads(f.read_text(encoding="utf-8")) for f in json_files]
        self._ensure_dirs()
        
        pointwise_inputs = []  # sllm1, sllm2, sllm3, base1, base2, base3
        pairwise_inputs = []   # turn1, turn2, turn3
        
        for i, data in enumerate(data_list, 1):
            s_code = data.get("sllm_code", "")
            b_code = data.get("baseline_code", "")
            task = data.get("simbench_prompt", "")
            
            # POINTWISE: S-LLM
            s_pointwise = POINTWISE_JUDGE_PROMPT.format(
                generated_code=s_code, pychrono_api_documentation=self.pychrono_api_docs, task_description=task
            )
            pointwise_inputs.append(s_pointwise)
            self._save_input(f"pointwise_sllm_turn{i}", s_pointwise)
            
            # POINTWISE: Baseline  
            b_pointwise = POINTWISE_JUDGE_PROMPT.format(
                generated_code=b_code, pychrono_api_documentation=self.pychrono_api_docs, task_description=task
            )
            pointwise_inputs.append(b_pointwise)
            self._save_input(f"pointwise_baseline_turn{i}", b_pointwise)
            
            # PAIRWISE: S-LLM vs Baseline
            pairwise = PAIRWISE_JUDGE_PROMPT.format(
                sllm_code=s_code, baseline_code=b_code, 
                pychrono_api_documentation=self.pychrono_api_docs, task_description=task
            )
            pairwise_inputs.append(pairwise)
            self._save_input(f"pairwise_turn{i}", pairwise)
            
            print(f"   Turn {i}: pointwise_sllm({len(s_code)//1000}K), pointwise_base({len(b_code)//1000}K), pairwise")
        
        print(f"\n✅ Созданы 9 файлов:")
        print(f"   6× pointwise_*.txt (sllm1-3 + baseline1-3)")
        print(f"   3× pairwise_turn*.txt")
        
        return [d.get("steel_text", "") for d in data_list], \
               [d.get("simbench_prompt", "") for d in data_list], \
               [d.get("sllm_code", "") for d in data_list], \
               [d.get("baseline_code", "") for d in data_list]

    def _save_input(self, filename: str, content: str):
        """Сохранить input как .txt (для копи-паста) и .json (метаданные)"""
        txt_file = self.judge_input_dir / f"{filename}.txt"
        json_file = self.judge_input_dir / f"{filename}.json"
        
        txt_file.write_text(content, encoding="utf-8")
        
        json_meta = {
            "type": filename,
            "prompt_type": "pointwise" if "pointwise" in filename else "pairwise",
            "chars": len(content),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        json_file.write_text(json.dumps(json_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ensure_dirs(self):
        """Создать необходимые директории"""
        self.judge_input_dir.mkdir(parents=True, exist_ok=True)
        self.judge_results_dir.mkdir(parents=True, exist_ok=True)

    def step2_wait_all_results(self, poll_interval: int = 10, timeout: int = 3600) -> Dict:
        """ШАГ 2: Ожидание 9 вердиктов (6 pointwise + 3 pairwise)"""
        print(f"\n⏳ ШАГ 2: Ожидание 9 J-LLM вердиктов...")
        print("📁 Нужны файлы в judge_results/:")
        print("   pointwise_sllm_turn[1-3].json, pointwise_baseline_turn[1-3].json")
        print("   pairwise_turn[1-3].json")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            results = list(self.judge_results_dir.glob("*.json"))
            if len(results) >= 9:
                print(f"\n✅ Найдено {len(results)}/9 вердиктов!")
                break
            print(f"⏳ Ожидание... ({len(results)}/9)", end='\r')
            time.sleep(poll_interval)
        
        # Парсинг
        verdicts = {"pointwise": {}, "pairwise": {}}
        for result_file in results:
            try:
                data = json.loads(result_file.read_text(encoding="utf-8"))
                score_match = re.search(r'\[\[(\d+(?:\.\d+)?)\]\]', str(data))
                score = float(score_match.group(1)) if score_match else data.get("score", 0.0)
                
                if "pointwise" in result_file.name:
                    model = "sllm" if "sllm" in result_file.name else "baseline"
                    turn = int(re.search(r'turn(\d+)', result_file.name).group(1))
                    verdicts["pointwise"][f"{model}_turn{turn}"] = {"score": score, "file": result_file.name}
                elif "pairwise" in result_file.name:
                    turn = int(re.search(r'turn(\d+)', result_file.name).group(1))
                    verdicts["pairwise"][f"turn{turn}"] = {"score": score, "file": result_file.name}
                    
                print(f"   ✅ {result_file.name}: {score:.1f}")
            except Exception as e:
                print(f"⚠️  {result_file.name}: {e}")
        
        return verdicts

    def step3_final_evaluation(self, prompts: List[str], sllm_codes: List[str], 
                             baseline_codes: List[str], verdicts: Dict) -> pd.DataFrame:
        """ШАГ 3: Финальная таблица с pointwise + pairwise"""
        print("\n🚀 ШАГ 3: Pointwise + Pairwise SimBench оценка")
        
        results = []
        turn_types = ["VAGUE", "SHARP", "COMPLEX"]
        
        for i in range(3):
            turn = i + 1
            s_pointwise = verdicts["pointwise"].get(f"sllm_turn{turn}", {}).get("score", 0)
            b_pointwise = verdicts["pointwise"].get(f"baseline_turn{turn}", {}).get("score", 0)
            pairwise = verdicts["pairwise"].get(f"turn{turn}", {}).get("score", 50)
            
            results.append({
                'Turn': turn,
                'Type': turn_types[i],
                'S-LLM_pointwise': f"{s_pointwise:.0f}",
                'Base_pointwise': f"{b_pointwise:.0f}",
                'Pairwise_SvsB': f"{pairwise:.0f}",
                'Pointwise_Winner': 'S-LLM' if s_pointwise > b_pointwise else 'Base',
                'Pairwise_Relative': f"{pairwise:.0f}%"
            })
            
            print(f"Turn {turn}: S-LLM={s_pointwise:.0f} | Base={b_pointwise:.0f} | Pairwise={pairwise:.0f}%")
        
        df = pd.DataFrame(results)
        return df


def main():
    print("🔥 SimBench v4.4 - POINTWISE + PAIRWISE J-LLM")
    print("6 pointwise + 3 pairwise = 9 оценок")
    print("=" * 60)
    
    evaluator = SimBenchSteelCastingEvaluator()
    
    # ШАГ 1: Генерация 9 inputs
    prompts, sllm_codes, baseline_codes, _ = evaluator.step1_generate_all_inputs()
    
    print("\n🎯 ГОТОВО! Копируйте 9 .txt файлов:")
    print("   pointwise_sllm_turn[1-3].txt → оценивают S-LLM")
    print("   pointwise_baseline_turn[1-3].txt → оценивают Baseline") 
    print("   pairwise_turn[1-3].txt → S-LLM vs Baseline")
    print("\n💾 Создайте 9 JSON в judge_results/:")
    print("   pointwise_sllm_turn1.json, pointwise_baseline_turn1.json, pairwise_turn1.json, etc.")
    print("   Формат: {'score': 85.0, 'verdict': '[[85.0]]...'}\n")
    
    input("\n⌨️  Enter после 9 вердиктов...")
    
    # ШАГ 2: Чтение результатов
    verdicts = evaluator.step2_wait_all_results()
    
    # ШАГ 3: Финальная таблица
    df = evaluator.step3_final_evaluation(prompts, sllm_codes, [], verdicts)
    
    print("\n🏆 SIMBENCH РЕЗУЛЬТАТЫ (Pointwise + Pairwise):")
    print(df.to_string(index=False))
    
    # Сохранение
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    df.to_csv(f"simbench_pointwise_pairwise_{timestamp}.csv", index=False)
    print(f"\n💾 simbench_pointwise_pairwise_{timestamp}.csv")
    
    print("\n🎓 Pointwise + Pairwise протокол завершен!")


if __name__ == "__main__":
    main()
