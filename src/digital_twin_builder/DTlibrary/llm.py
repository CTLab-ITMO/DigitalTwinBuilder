from langchain_ollama import OllamaLLM
import logging

logger = logging.getLogger("LLMService")

class LLMService:
    def __init__(self, model_name: str = "qwen3:4b", temperature: float = 0.1):
        self.model_name = model_name
        try:
            self.model = OllamaLLM(model=model_name, temperature=temperature, base_url="http://localhost:11434")
            logger.info(f"Initialized OllamaLLM model={model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize OllamaLLM: {e}")
            raise

    def generate(self, prompt: str, system_prompt: str = None, max_tokens: int = 1024) -> str:
        full_prompt = prompt
        if system_prompt:
            full_prompt = system_prompt.strip() + "\n\n" + prompt.strip()

        try:
            response = self.model.invoke(full_prompt)
            if isinstance(response, dict) and 'content' in response:
                return response['content']
            return str(response)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            raise

    def generate_json(self, prompt: str, system_prompt: str = None, max_tokens: int = 1024):
        text = self.generate(prompt, system_prompt=system_prompt, max_tokens=max_tokens)
        try:
            import json as _json
            return _json.loads(text)
        except Exception:
            return {"raw": text}

llm_service = LLMService()
