from transformers import pipeline
import os

class LLMService:
    def __init__(self):
        self.models = {
            'user_interaction': None,
            'database': None,
            'digital_twin': None
        }
        self._load_models()

    def _load_models(self):
        try:
            self.models['user_interaction'] = pipeline(
                "text-generation", 
                model="MTSAIR/Cotype-Nano",
                device="cuda" if os.environ.get('USE_CUDA', 'false').lower() == 'true' else "cpu"
            )
            
            self.models['database'] = pipeline(
                "text-generation",
                model="abdulmannan-01/qwen-2.5-1.5b-finetuned-for-sql-generation",
                device="cuda" if os.environ.get('USE_CUDA', 'false').lower() == 'true' else "cpu"
            )
            
            self.models['digital_twin'] = pipeline(
                "text-generation",
                model="bigcode/starcoder2-3b",
                device="cuda" if os.environ.get('USE_CUDA', 'false').lower() == 'true' else "cpu"
            )
            
        except Exception as e:
            print(f"Error loading models: {e}")
            raise

    def generate(self, task_type: str, prompt: str, max_length: int = 1024) -> str:
        if task_type not in self.models:
            raise ValueError(f"Invalid task type: {task_type}")
        
        try:
            response = self.models[task_type](
                prompt,
                max_length=max_length,
                num_return_sequences=1
            )[0]['generated_text']
            return response
        except Exception as e:
            print(f"Generation failed: {e}")
            raise

llm_service = LLMService()