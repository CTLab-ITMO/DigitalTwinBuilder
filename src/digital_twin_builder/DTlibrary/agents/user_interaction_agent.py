# user_interaction_agent.py
from .base_agent import BaseAgent
import json

class UserInteractionAgent(BaseAgent):
    def __init__(self):
        super().__init__("UserInteractionAgent")
        self.log("Using mock user interaction model")
        
        self.mock_response = """{
            "introduction": "Mock interview with employee ID 12345",
            "general_information": {
                "enterprise_activity": "Manufacturing of industrial equipment",
                "organizational_structure": "Production, Quality Control, Maintenance, Logistics",
                "production_area": "5000 sq.m."
            },
            "digital_twin": {
                "priority_process": {
                    "process_name": "Assembly line 3",
                    "reason": "Most critical for production with highest failure rate"
                },
                "process_description": "1. Parts arrival 2. Pre-assembly 3. Main assembly 4. Quality check 5. Packaging",
                "problems": "Frequent delays at quality check station"
            },
            "conclusion": "Thank you for participating in the digital twin interview"
        }"""

    def run(self, input_data=None):
        """Implementation of abstract method from BaseAgent"""
        try:
            return self.conduct_interview()
        except Exception as e:
            self.log(f"Error in run method: {str(e)}", "error")
            raise

    def conduct_interview(self):
        """Return mock interview results"""
        self.log("Returning mock interview results")
        try:
            return json.loads(self.mock_response)
        except json.JSONDecodeError:
            return {"response": self.mock_response}
        except Exception as e:
            self.log(f"Mock interview failed: {str(e)}", "error")
            raise