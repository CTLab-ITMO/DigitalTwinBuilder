from base_agent import BaseAgent
from transformers import pipeline
import json
import requests
import time
import logging
import sys
import signal
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(self.name)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    def log(self, message: str, level: str = "info"):
        """Logging helper method"""
        getattr(self.logger, level)(message)

    def run(self, interval: float = 2.0):
        self.running = True
        logger.info(f"Agent {self.agent_id} started. Polling interval: {interval}s")
        heartbeat_interval = 30
        last_heartbeat = time.time()
        
        while self.running:
            try:
                current_time = time.time()
                
                if current_time - last_heartbeat > heartbeat_interval:
                    self.send_heartbeat()
                    last_heartbeat = current_time
                
                processed = self.run_once()
                
                if not processed:
                    time.sleep(interval)
                    
            except KeyboardInterrupt:
                logger.info("Interrupted by user")
                self.stop()
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {str(e)}")
                time.sleep(interval)

    def run_once():
        task = self.poll_task()

        if task:
            try:
                result = self.process_task(task)
            except Exception as e:
                logger.error(f"Task processing failed: {str(e)}")
                self.submit_result(
                    task["task_id"], 
                    "", 
                    error=f"Processing error: {str(e)}"
                )
            return True
        return False

    def submit_result(self, task_id: str, result: str, error: Optional[str] = None):
        """
        Submit the task result back to the API server.
        
        Args:
            task_id: ID of the task
            result: Result text
            error: Optional error message
        """
        try:
            response = requests.post(
                f"{self.api_url}/tasks/{task_id}/result",
                json={
                    "result": result,
                    "error": error
                },
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"Result submitted for task {task_id[:8]}")
            else:
                logger.error(f"Failed to submit result: {response.status_code} - {response.text}")
                
        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to API server to submit result")
            raise
        except Exception as e:
            logger.error(f"Result submission error: {str(e)}")
            raise

    @abstractmethod
    def process_task(self, task):
        pass
