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
        self.modification_system_prompt = (
            "You are an expert in modifying configurations for digital twins of industrial facilities. "
            "Your task is to take an existing configuration (in JSON format) and a natural language instruction describing changes to be made, "
            "and then produce a new, updated configuration JSON reflecting those changes. "
            "Ensure the structure remains consistent and valid. Only return the updated JSON object, nothing else."
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

    def modify_config(self, old_config: Dict[str, Any], modification_instructions: str) -> Dict[str, Any]:
        """
        Modifies an existing digital twin configuration based on natural language instructions.
        """
        self.log("Modifying digital twin configuration based on user instructions.")
        prompt = f"""
        Here is the current digital twin configuration:
        {json.dumps(old_config, ensure_ascii=False, indent=2)}

        Please modify the configuration according to the following instructions:
        {modification_instructions}

        Return ONLY the updated configuration in valid JSON format.
        """
        try:
            result = self.llm.generate_json(prompt, system_prompt=self.modification_system_prompt, max_tokens=2048)
            if isinstance(result, dict):
                 if 'raw' in result:
                     raw_text = result['raw']
                     try:
                         parsed_json = json.loads(raw_text)
                         return parsed_json
                     except json.JSONDecodeError:
                         return {"error": "Could not parse modified config JSON", "raw_output": raw_text}
                 else:
                     return result
            else:
                return {"error": "LLM did not return a dictionary", "output": str(result)}
        except Exception as e:
            self.log(f"Configuration modification failed: {str(e)}", "error")
            return {"error": f"Modification failed due to: {str(e)}"}