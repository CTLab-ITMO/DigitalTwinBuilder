from .base_agent import BaseAgent
from transformers import pipeline
import json
from typing import Dict, Any

class DatabaseAgent(BaseAgent):
    def __init__(self):
        super().__init__("DatabaseAgent")
        try:
            self.model = pipeline("text-generation", 
                                model="abdulmannan-01/qwen-2.5-1.5b-finetuned-for-sql-generation")
        except Exception as e:
            self.log(f"Failed to load database model: {str(e)}", "error")
            raise

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
        {json.dumps(translated_reqs, ensure_ascii=False)}
        
        The schema should include tables for:
        - Sensor data (temperature, pressure, vibration, etc.)
        - Equipment status
        - Production quality metrics
        - Material composition
        
        Output should be a JSON with tables, columns, data types, constraints and relationships."""
        
        try:
            response = self.model(
                prompt, 
                max_length=2048, 
                num_return_sequences=1
            )[0]['generated_text']
            return self._parse_response(response)
        except Exception as e:
            self.log(f"Schema generation failed: {str(e)}", "error")
            raise

    def _parse_response(self, response: str) -> Dict[str, Any]:
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            self.log("Failed to parse JSON response, returning raw text", "warning")
            return {"sql": response}