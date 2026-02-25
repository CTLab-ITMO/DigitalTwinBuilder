from langchain_ollama import OllamaLLM
import logging
import json
import re

logger = logging.getLogger("LLMService")

class LLMService:
    def __init__(self, model_name: str = "deepseek-v3.1:671b-cloud", temperature: float = 0.1):
        self.model_name = model_name
        self.model = OllamaLLM(
            model=model_name,
            temperature=temperature,
            base_url="http://localhost:11434"
        )
        logger.info(f"Initialized OllamaLLM model={model_name}")

    def generate(self, prompt: str, system_prompt: str = None, max_tokens: int = 1024) -> str:
        full_prompt = prompt
        if system_prompt:
            full_prompt = system_prompt.strip() + "\n" + prompt.strip()
        response = self.model.invoke(full_prompt)
        
        return str(response)

    def extract_json_from_text(self, text: str) -> dict:
        """Извлекает JSON из текста, который может содержать маркеры кода."""
        
        pattern = r'```json\s*({.*?})\s*```'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            json_str = match.group(1)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse extracted JSON: {json_str[:200]}...")
                pass

        
        
        try:
            
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = text[start:end+1]
                return json.loads(json_str)
        except Exception as e:
            logger.warning(f"Failed to parse JSON from raw text: {e}")

        
        return {"raw_output": text}

    def generate_json(self, prompt: str, system_prompt: str = None, max_tokens: int = 1024):
        text = self.generate(prompt, system_prompt, max_tokens)
        logger.debug(f"Raw LLM output: {text[:500]}...") 
        try:
            
            parsed_json = self.extract_json_from_text(text)
            return parsed_json
        except Exception as e:
            logger.error(f"Error in generate_json: {e}")
            
            return {"raw": text}


llm_service = LLMService()