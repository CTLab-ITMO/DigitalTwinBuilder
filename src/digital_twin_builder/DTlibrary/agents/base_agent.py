import logging
from abc import ABC, abstractmethod
from digital_twin_builder.DTlibrary.llm import llm_service

class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(self.name)
        self.llm = llm_service
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    @abstractmethod
    def run(self, *args, **kwargs):
        """Main method to execute agent's functionality"""
        pass

    def log(self, message: str, level: str = "info"):
        """Logging helper method"""
        getattr(self.logger, level)(message)