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
        """Implementation of abstract method from BaseAgent"""
        try:
            if not requirements:
                raise ValueError("No requirements provided")
            return self.generate_schema(requirements)
        except Exception as e:
            self.log(f"Error in run method: {str(e)}", "error")
            raise

    def generate_schema(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Generate database schema from requirements"""
        self.log("Generating database schema")
        prompt = f"""Create PostgreSQL schema for digital twin with these requirements:
        {json.dumps(requirements)}
        Output JSON with tables, columns, and relationships."""
        
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
        """Parse the model response into structured data"""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            self.log("Failed to parse JSON response, returning raw text", "warning")
            return {"sql": response}