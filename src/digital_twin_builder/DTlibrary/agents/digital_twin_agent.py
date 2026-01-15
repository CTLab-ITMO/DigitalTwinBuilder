from digital_twin_builder.DTlibrary.agents.base_agent import BaseAgent
import json
from typing import Dict, Any

class DigitalTwinAgent(BaseAgent):
    def __init__(self):
        super().__init__("DigitalTwinAgent")
        self.config_system_prompt = ("You are an expert in designing digital twins for industrial facilities. "
                                     "Based on requirements and a database schema, produce a structured JSON configuration. "
                                     "Include components, data flows, visualization layout, alerts and KPIs. "
                                     "Return only valid JSON.")
        self.simulation_system_prompt = (
            "You are an expert Python developer specializing in the PyChrono multi-physics simulator. "
            "Based on the provided requirements for a digital twin and the database schema, generate a complete, executable Python script that creates a PyChrono simulation. "
            "The script should: "
            "- Initialize the PyChrono system. "
            "- Define physical bodies, materials, joints, and any other necessary components based on the requirements. "
            "- Set up the simulation environment (terrain, gravity, etc.). "
            "- Implement the main simulation loop. "
            "- Log or output simulation data that corresponds to the tables and fields defined in the database schema. "
            "- Include necessary imports, comments, and follow PyChrono best practices. "
            "The output should be only the Python code, without any markdown code block markers (no ```python or ```)."
        )

    def run(self, requirements: Dict[str, Any] = None, db_schema: Dict[str, Any] = None) -> Dict[str, Any]:
        try:
            if not requirements or not db_schema:
                raise ValueError("Missing required parameters for simulation generation")

            simulation_code = self.generate_simulation_code(requirements, db_schema)
            return simulation_code
        except Exception as e:
            self.log(f"Error in run method: {str(e)}", "error")
            raise

    def generate_simulation_code(self, requirements: Dict[str, Any], db_schema: Dict[str, Any]) -> str:
        self.log("Configuring digital twin simulation code with LLM")
        prompt = f"""Generate a complete PyChrono simulation script based on these requirements and database schema.

Requirements:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Database Schema:
{json.dumps(db_schema, ensure_ascii=False, indent=2)}

The Python script should be ready to execute and represent the digital twin as described.
"""

        try:
            result = self.llm.generate(prompt, system_prompt=self.simulation_system_prompt, max_tokens=4096)
            return result
        except Exception as e:
            self.log(f"Simulation code generation failed: {str(e)}", "error")
            raise

    def configure_twin_old(self, requirements: Dict[str, Any], db_schema: Dict[str, Any]) -> Dict[str, Any]:
        self.log("Configuring digital twin (old method) with LLM")
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
            result = self.llm.generate_json(prompt, system_prompt=self.config_system_prompt, max_tokens=2048)
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