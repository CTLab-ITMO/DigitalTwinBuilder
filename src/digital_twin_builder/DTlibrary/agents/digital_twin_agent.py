from .base_agent import BaseAgent
from transformers import pipeline
import json
from typing import Dict, Any

class DigitalTwinAgent(BaseAgent):
    def __init__(self):
        super().__init__("DigitalTwinAgent")
        try:
            self.model = pipeline("text-generation", model="bigcode/starcoder2-3b") #bigcode/starcoder2-7b
        except Exception as e:
            self.log(f"Failed to load digital twin model: {str(e)}", "error")
            raise

    def run(self, requirements: Dict[str, Any] = None, db_schema: Dict[str, Any] = None) -> Dict[str, Any]:
        """Implementation of abstract method from BaseAgent"""
        try:
            if not requirements or not db_schema:
                raise ValueError("Missing required parameters")
            return self.configure_twin(requirements, db_schema)
        except Exception as e:
            self.log(f"Error in run method: {str(e)}", "error")
            raise

    def configure_twin(self, requirements: Dict[str, Any], db_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Configure digital twin from requirements and db schema"""
        self.log("Configuring digital twin")
        prompt = f"""Create digital twin configuration with:
        Requirements: {json.dumps(requirements)}
        Database Schema: {json.dumps(db_schema)}
        Output JSON with components, data flows, and visualization setup."""
        
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
        """Parse the model response into structured data"""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            self.log("Failed to parse JSON response, returning raw text", "warning")
            return {"configuration": response}