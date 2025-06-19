import logging
from abc import ABC, abstractmethod

class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(self.name)
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    @abstractmethod
    def run(self, *args, **kwargs):
        raise NotImplementedError

    def log(self, message: str, level: str = "info"):
        getattr(self.logger, level)(message)