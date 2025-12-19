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
        self.logger.info(f"Agent {self.agent_id} started. Polling interval: {interval}s")
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
                self.logger.info("Interrupted by user")
                self.stop()
            except Exception as e:
                self.logger.error(f"Unexpected error in main loop: {str(e)}")
                time.sleep(interval)

    def run_once(self):
        task = self.poll_task()

        if task:
            try:
                result = self.process_task(task)
            except Exception as e:
                self.logger.error(f"Task processing failed: {str(e)}")
                self.submit_result(
                    task["task_id"], 
                    "", 
                    error=f"Processing error: {str(e)}"
                )
            return True
        return False
    
    def submit_result(self, task_id: str, result: str, error: Optional[str] = None):
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
                self.logger.info(f"Result submitted for task {task_id[:8]}")
            else:
                self.logger.error(f"Failed to submit result: {response.status_code} - {response.text}")
                
        except requests.exceptions.ConnectionError:
            self.logger.error("Cannot connect to API server to submit result")
            raise
        except Exception as e:
            self.logger.error(f"Result submission error: {str(e)}")
            raise
    
    def send_heartbeat(self):
        try:
            requests.post(
                f"{self.api_url}/agent/poll",
                json={"agent_id": self.agent_id},
                timeout=5
            )
            logger.debug("Heartbeat sent")
        except:
            pass

    def poll_task(self) -> Optional[Dict[str, Any]]:
        try:
            response = requests.post(
                f"{self.api_url}/agent/poll",
                json={
                    "agent_id": self.agent_id,
                    "capabilities": self.capabilities
                },
                timeout=30
            )

            if response.status_code == 200:
                task_data = response.json()
                if task_data:
                logger.info(f"Received task: {task_data['task_id'][:8]}")
                    return task_data
                else:
                    logger.debug("No tasks available")
            elif response.status_code == 204:
                logger.debug("No tasks: no content")
                pass
            else:
                logger.warning(f"Unexpected response: {response.status_code}")

        except requests.exceptions.Timeout:
            logger.debug("Poll timeout (no tasks)")
        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to API server")
        except Exception as e:
            logger.error(f"Poll error: {str(e)}")
        sys.stdout.flush()
        return None

    def stop(self):
        self.running = False
        logger.info(f"Agent {self.agent_id} stopped")

    @abstractmethod
    def process_task(self, task):
        pass
