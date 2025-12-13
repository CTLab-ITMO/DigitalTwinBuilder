from digital_twin_builder.DTlibrary.agents.base_agent import BaseAgent
import json
from typing import Dict, Any

class DigitalTwinAgent(BaseAgent):
    def __init__(self):
        super().__init__("DigitalTwinAgent")
        self.system_prompt = ("You are an expert in designing digital twins for industrial facilities. " 
                              "Based on requirements and a database schema, produce a structured JSON configuration. " 
                              "Include components, data flows, visualization layout, alerts and KPIs. " 
                              "Return only valid JSON.")

    def run(self, requirements: Dict[str, Any] = None, db_schema: Dict[str, Any] = None) -> Dict[str, Any]:
        try:
            if not requirements or not db_schema:
                raise ValueError("Missing required parameters")
            return self.configure_twin(requirements, db_schema)
        except Exception as e:
            self.log(f"Error in run method: {str(e)}", "error")
            raise

    def configure_twin(self, requirements: Dict[str, Any], db_schema: Dict[str, Any]) -> Dict[str, Any]:
        self.log("Configuring digital twin with LLM")
        prompt = f"""Create a comprehensive digital twin configuration for a metallurgical production facility.

Requirements: {json.dumps(requirements, ensure_ascii=False)}
Database Schema: {json.dumps(db_schema, ensure_ascii=False)}

The configuration should include:
1. Components: Data collection, analytics, visualization modules
2. Data flows: Between components with protocols and frequencies
3. Visualization: Dashboard layout, refresh rates, alerts setup
4. KPIs: Key performance indicators to monitor

Output should be a well-structured JSON document."""

        try:
            result = self.llm.generate_json(prompt, system_prompt=self.system_prompt, max_tokens=2048)
            if isinstance(result, dict) and 'raw' in result:
                raw = result['raw']
                try:
                    return json.loads(raw)
                except Exception:
                    return {"configuration": raw}
            return result
        except Exception as e:
            self.log(f"Configuration failed: {str(e)}", "error")
            raise
