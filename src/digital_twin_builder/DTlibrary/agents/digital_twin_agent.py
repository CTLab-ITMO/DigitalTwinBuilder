from .base_agent import BaseAgent
from transformers import pipeline
import json

class DigitalTwinAgent(BaseAgent):
    def __init__(self):
        super().__init__("DigitalTwinAgent")
        self.model = pipeline("text-generation", model="bigcode/starcoder2-3b") #bigcode/starcoder2-7b
        
    def configure_twin(self, requirements: dict, db_schema: dict):
        self.log("Configuring digital twin")
        prompt = f"""Create digital twin configuration with:
        Requirements: {json.dumps(requirements)}
        Database Schema: {json.dumps(db_schema)}
        Output JSON with components, data flows, and visualization setup."""
        
        response = self.model(prompt, max_length=2048, num_return_sequences=1)[0]['generated_text']
        return self._parse_response(response)
    
    def _parse_response(self, response):
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"configuration": response}