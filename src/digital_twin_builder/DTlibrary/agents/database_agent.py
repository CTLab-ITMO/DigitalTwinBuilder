from digital_twin_builder.DTlibrary.agents.base_agent import BaseAgent
import json
from typing import Dict, Any

class DatabaseAgent(BaseAgent):
    def __init__(self):
        super().__init__("DatabaseAgent")
        self.system_prompt = ("You are an expert SQL architect. Given production requirements, " 
                              "produce a PostgreSQL schema described as valid JSON. " 
                              "The JSON should contain tables, columns, types, constraints and relationships. " 
                              "Do not include explanations or additional commentary, only the JSON.")

    def run(self, requirements: Dict[str, Any] = None) -> Dict[str, Any]:
        try:
            if not requirements:
                raise ValueError("No requirements provided")
            return self.generate_schema(requirements)
        except Exception as e:
            self.log(f"Error in run method: {str(e)}", "error")
            raise

    def generate_schema(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        self.log("Generating database schema with LLM")

        translated_reqs = {
            "general_info": requirements.get("общая_информация", ""),
            "production_processes": requirements.get("производственные_процессы", ""),
            "data_monitoring": requirements.get("данные_и_мониторинг", ""),
            "twin_requirements": requirements.get("требования_к_цифровому_двойнику", "")
        }

        prompt = f"""Create a PostgreSQL schema for a metallurgical production digital twin based on these requirements:
{json.dumps(translated_reqs, ensure_ascii=False, indent=2)}

The schema should include tables for:
- Sensor data (temperature, pressure, vibration, etc.)
- Equipment status
- Production quality metrics
- Material composition

Output should be a JSON with tables, columns, data types, constraints and relationships."""

        try:
            result = self.llm.generate_json(prompt, system_prompt=self.system_prompt, max_tokens=2048)
            if isinstance(result, dict) and 'raw' in result:
                raw = result['raw']
                try:
                    return json.loads(raw)
                except Exception:
                    return {"sql": raw}
            return result
        except Exception as e:
            self.log(f"Schema generation failed: {str(e)}", "error")
            raise
