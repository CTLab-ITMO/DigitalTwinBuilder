from .base_agent import BaseAgent
from transformers import pipeline
import json
from typing import Dict, Any

class DigitalTwinAgent(BaseAgent):
    def __init__(self):
        super().__init__("DigitalTwinAgent")
        try:
            self.model = pipeline("text-generation", model="bigcode/starcoder2-3b")
        except Exception as e:
            self.log(f"Failed to load digital twin model: {str(e)}", "error")
            raise

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
        prompt = f"""Create a comprehensive digital twin configuration for a metallurgical production facility with:
        
        Requirements: {json.dumps(requirements)}
        Database Schema: {json.dumps(db_schema)}
        
        The configuration should include:
        1. Components: Data collection, analytics, visualization modules
        2. Data flows: Between components with protocols and frequencies
        3. Visualization: Dashboard layout, refresh rates, alerts setup
        4. KPIs: Key performance indicators to monitor
        
        Output should be a well-structured JSON document."""
        
        try:
            response = self.model(
                prompt, 
                max_length=2048, 
                num_return_sequences=1
            )[0]['generated_text']
            return self._parse_response(response)
        except Exception as e:
            self.log(f"Configuration failed: {str(e)}", "error")
            raise

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Parse the mock response into structured data"""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            self.log("Failed to parse JSON response, returning raw text", "warning")
            return {"configuration": response}