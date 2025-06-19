from .base_agent import BaseAgent
from transformers import pipeline
import json

class DatabaseAgent(BaseAgent):
    def __init__(self):
        super().__init__("DatabaseAgent")
        self.model = pipeline("text-generation", model="abdulmannan-01/qwen-2.5-1.5b-finetuned-for-sql-generation")
        
    def generate_schema(self, requirements: dict):
        self.log("Generating database schema")
        prompt = f"""Task: You are a database design expert. Develop a database schema for a given application, considering its digital twin aspects.

Requirements:
You will receive a description of the application and its data storage requirements, focusing on the needs of its digital twin representation.
Design the database schema, including tables/collections, columns/fields, data types, and relationships.
Provide code (SQL, JSON Schema, etc.) to create the database structure.
Provide queries to perform basic operations (CRUD - Create, Read, Update, Delete) relevant to the digital twin.
Consider scalability, performance, and security factors crucial for the digital twin's responsiveness and reliability.  Include aspects of data synchronization and real-time updates if applicable.

Input:
Application description and data storage requirements (focusing on digital twin): application_description
Preferred database type (if any): preferred_database_type

Instructions:
1.  Analyze the application description and identify key entities and their attributes required for the digital twin.
2.  Select an appropriate database type based on these requirements (if no preferred type is specified).
3.  Design the database schema, considering the selected type.  Incorporate elements that facilitate the digital twin's real-time data reflection.
4.  Generate code to create the database structure.
5.  Provide example queries for basic operations critical for the digital twin's functionality.
6.  Justify your database type selection and schema design decisions, especially regarding the digital twin's needs.
        
Create PostgreSQL schema for digital twin with these requirements:
{json.dumps(requirements)}
Output JSON with tables, columns, and relationships."""
         
        response = self.model(prompt, max_length=2048, num_return_sequences=1)[0]['generated_text']
        return self._parse_response(response)
    
    def _parse_response(self, response):
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"sql": response}