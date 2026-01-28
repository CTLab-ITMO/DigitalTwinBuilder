from digital_twin_builder.DTlibrary.agents.base_agent import BaseAgent
import json
from typing import Dict, Any


class DigitalTwinAgent(BaseAgent):
    def __init__(self):
        super().__init__("DigitalTwinAgent")
        self.config_system_prompt = (
            "You are an expert in designing digital twins for industrial facilities. "
            "Based on requirements and a database schema, produce a structured JSON configuration. "
            "Include components, data flows, visualization layout, alerts and KPIs. "
            "Return only valid JSON without markdown formatting."
        )
        self.simulation_system_prompt = (
            "You are an expert Python developer specializing in the PyChrono multi-physics simulator. "
            "Based on the provided requirements for a digital twin and the database schema, generate a complete, executable Python script that creates a PyChrono simulation. "
            "The script should: "
            "- Initialize the PyChrono system. "
            "- Define physical bodies, materials, joints, and any other necessary components based on the requirements. "
            "- Set up the simulation environment (terrain, gravity, etc.). "
            "- Implement the main simulation loop. "
            "- Log or output simulation data that corresponds to the tables and fields defined in the database schema. "
            "- Include necessary imports, comments, and follow PyChrono best practices. "
            "The output should be only the Python code, without any markdown code block markers (no ```python or ```)."
        )
        self.database_system_prompt = (
            "You are a PostgreSQL database expert. "
            "Based on the provided database schema in JSON format, generate complete SQL code to create all tables, indexes, and constraints. "
            "The SQL should be production-ready and follow PostgreSQL best practices. "
            "Include CREATE TABLE statements, indexes, and any necessary comments. "
            "Return only the SQL code without markdown formatting."
        )
        self.modification_system_prompt = (
            "You are an expert in modifying configurations for digital twins of industrial facilities. "
            "Your task is to take an existing configuration (in JSON format) and a natural language instruction describing changes to be made, "
            "and then produce a new, updated configuration JSON reflecting those changes. "
            "Ensure the structure remains consistent and valid. Only return the updated JSON object, nothing else."
        )

    def run(self, requirements: Dict[str, Any] = None, db_schema: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Основной метод для генерации конфигурации цифрового двойника
        """
        try:
            if not requirements or not db_schema:
                raise ValueError("Missing required parameters: requirements and db_schema")
            
            config = self.generate_configuration(requirements, db_schema)
            return config
        except Exception as e:
            self.log(f"Error in run method: {str(e)}", "error")
            raise

    def generate_configuration(self, requirements: Dict[str, Any], db_schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Генерирует конфигурацию цифрового двойника на основе требований и схемы БД
        """
        self.log("Generating digital twin configuration with LLM")
        
        prompt = f"""Create a comprehensive digital twin configuration for the industrial facility.

Requirements:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Database Schema:
{json.dumps(db_schema, ensure_ascii=False, indent=2)}

The configuration should include:
1. Components: Data collection modules, analytics engines, ML models, visualization dashboards
2. Data flows: Connections between components with protocols (OPC-UA, MQTT, REST, WebSocket) and update frequencies
3. Visualization: Dashboard layout, widget types, refresh rates, color schemes
4. Alerts: Threshold-based alerts with severity levels (info, warning, critical, emergency)
5. KPIs: Key performance indicators with target values and measurement methods

Return a well-structured JSON configuration that can be used to deploy the digital twin system.
Start directly with the opening brace {{."""

        try:
            result = self.llm.generate(
                prompt=prompt,
                system_prompt=self.config_system_prompt,
                max_tokens=2048
            )
            
            cleaned_result = self._clean_markdown(result)
            
            try:
                config = json.loads(cleaned_result)
                self.log("Successfully generated configuration")
                return config
            except json.JSONDecodeError as e:
                self.log(f"Failed to parse JSON: {str(e)}", "warning")
                return self._get_default_configuration(requirements, db_schema)
                
        except Exception as e:
            self.log(f"Configuration generation failed: {str(e)}", "error")
            return self._get_default_configuration(requirements, db_schema)

    def generate_simulation_code(self, requirements: Dict[str, Any], db_schema: Dict[str, Any]) -> str:
        """
        Генерирует Python код для симуляции PyChrono
        """
        self.log("Generating PyChrono simulation code with LLM")
        
        prompt = f"""Generate a complete PyChrono simulation script for the digital twin.

Requirements:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Database Schema:
{json.dumps(db_schema, ensure_ascii=False, indent=2)}

The Python script should:
1. Import necessary PyChrono modules
2. Initialize the Chrono system
3. Create physical bodies representing equipment (furnaces, crystallizers, rollers, etc.)
4. Set up materials with appropriate properties (steel, refractory, etc.)
5. Define joints and constraints between bodies
6. Implement sensors to measure simulation parameters
7. Create a simulation loop that:
   - Steps the simulation forward in time
   - Collects sensor data
   - Logs data that matches the database schema tables
8. Include error handling and proper cleanup

The code should be production-ready and executable. Do not include markdown formatting or code blocks.
Start directly with import statements."""

        try:
            result = self.llm.generate(
                prompt=prompt,
                system_prompt=self.simulation_system_prompt,
                max_tokens=4096
            )
            
            cleaned_code = self._clean_code_blocks(result)
            
            self.log("Successfully generated simulation code")
            return cleaned_code
            
        except Exception as e:
            self.log(f"Simulation code generation failed: {str(e)}", "error")
            return self._get_default_simulation_code(requirements)

    def generate_database_code(self, db_schema: Dict[str, Any]) -> str:
        """
        Генерирует SQL код для создания базы данных
        """
        self.log("Generating SQL database code")
        
        prompt = f"""Generate complete PostgreSQL SQL code to create the database schema.

Database Schema:
{json.dumps(db_schema, ensure_ascii=False, indent=2)}

The SQL should include:
1. CREATE TABLE statements for all tables with proper column types and constraints
2. PRIMARY KEY and FOREIGN KEY constraints
3. CREATE INDEX statements for performance optimization
4. Comments describing each table and important columns
5. Any necessary sequences or triggers

The SQL should be production-ready and follow PostgreSQL best practices.
Do not include markdown formatting. Start directly with SQL statements."""

        try:
            result = self.llm.generate(
                prompt=prompt,
                system_prompt=self.database_system_prompt,
                max_tokens=3072
            )
            
            cleaned_sql = self._clean_code_blocks(result)
            
            self.log("Successfully generated SQL code")
            return cleaned_sql
            
        except Exception as e:
            self.log(f"SQL generation failed: {str(e)}", "error")
            return self._get_default_sql_code(db_schema)

    def modify_config(self, old_config: Dict[str, Any], modification_instructions: str) -> Dict[str, Any]:
        """
        Модифицирует существующую конфигурацию на основе инструкций пользователя
        """
        self.log("Modifying digital twin configuration based on user instructions")
        
        prompt = f"""Here is the current digital twin configuration:
{json.dumps(old_config, ensure_ascii=False, indent=2)}

Please modify the configuration according to the following instructions:
{modification_instructions}

Return ONLY the updated configuration in valid JSON format without markdown formatting.
Start directly with the opening brace {{."""

        try:
            result = self.llm.generate(
                prompt=prompt,
                system_prompt=self.modification_system_prompt,
                max_tokens=2048
            )
            
            cleaned_result = self._clean_markdown(result)
            
            try:
                modified_config = json.loads(cleaned_result)
                self.log("Successfully modified configuration")
                return modified_config
            except json.JSONDecodeError:
                self.log("Failed to parse modified config", "warning")
                return old_config
                
        except Exception as e:
            self.log(f"Configuration modification failed: {str(e)}", "error")
            return old_config

    def _clean_markdown(self, text: str) -> str:
        """Удаляет markdown блоки из текста"""
        cleaned = text.strip()
        
        if cleaned.startswith("```json"):
            cleaned = cleaned.replace("```json", "", 1)
        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```", "", 1)
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        
        return cleaned.strip()

    def _clean_code_blocks(self, text: str) -> str:
        """Удаляет markdown блоки кода"""
        cleaned = text.strip()
        
        if cleaned.startswith("```python"):
            cleaned = cleaned.replace("```python", "", 1)
        if cleaned.startswith("```sql"):
            cleaned = cleaned.replace("```sql", "", 1)
        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```", "", 1)
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        
        return cleaned.strip()

    def _get_default_configuration(self, requirements: Dict[str, Any], db_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Возвращает базовую конфигурацию если LLM не смог сгенерировать"""
        production_type = requirements.get("production_type", "industrial facility")
        
        return {
            "name": f"Digital Twin for {production_type}",
            "version": "1.0",
            "components": [
                {
                    "name": "data_collection",
                    "type": "sensor_aggregator",
                    "sensors": requirements.get("sensors", []),
                    "update_frequency": requirements.get("update_frequency", "1s")
                },
                {
                    "name": "analytics_engine",
                    "type": "data_processor",
                    "analytics": ["real_time_monitoring", "anomaly_detection", "predictive_maintenance"]
                },
                {
                    "name": "visualization_dashboard",
                    "type": "web_interface",
                    "widgets": ["real_time_charts", "kpi_metrics", "alert_panel", "equipment_status"]
                }
            ],
            "data_flows": [
                {
                    "from": "data_collection",
                    "to": "database",
                    "protocol": "REST",
                    "frequency": "real-time"
                },
                {
                    "from": "database",
                    "to": "analytics_engine",
                    "protocol": "SQL",
                    "frequency": "1s"
                },
                {
                    "from": "analytics_engine",
                    "to": "visualization_dashboard",
                    "protocol": "WebSocket",
                    "frequency": "real-time"
                }
            ],
            "visualization": {
                "layout": "grid",
                "refresh_rate": 1000,
                "theme": "industrial"
            },
            "alerts": requirements.get("critical_parameters", {}),
            "kpis": [
                "equipment_uptime",
                "production_efficiency",
                "quality_score",
                "energy_consumption"
            ]
        }

    def _get_default_simulation_code(self, requirements: Dict[str, Any]) -> str:
        return f"""# PyChrono Simulation for Digital Twin
# Generated for: {requirements.get('production_type', 'Industrial Facility')}

import pychrono as chrono
import pychrono.irrlicht as chronoirr
import numpy as np
import time
from datetime import datetime

# Initialize Chrono system
system = chrono.ChSystemNSC()
system.Set_G_acc(chrono.ChVectorD(0, -9.81, 0))

# TODO: Add physical bodies based on equipment
# TODO: Set up materials and properties
# TODO: Define joints and constraints
# TODO: Implement sensor readings
# TODO: Create simulation loop

print("PyChrono simulation initialized")
print("Equipment: {requirements.get('equipment', [])}")
print("Sensors: {requirements.get('sensors', [])}")

# Main simulation loop
simulation_time = 0
time_step = 0.01

while simulation_time < 10:  # 10 seconds simulation
    system.DoStepDynamics(time_step)
    simulation_time += time_step
    
    # Log sensor data
    if int(simulation_time * 100) % 100 == 0:  # Every second
        print(f"Time: {{simulation_time:.2f}}s")
    
print("Simulation completed")
"""

    def _get_default_sql_code(self, db_schema: Dict[str, Any]) -> str:
        """Возвращает базовый SQL код"""
        sql_parts = ["-- PostgreSQL Database Schema", "-- Generated for Digital Twin", ""]
        
        schema_data = db_schema.get("database_schema", db_schema)
        tables = schema_data.get("tables", [])
        
        for table in tables:
            table_name = table.get("name", "unknown_table")
            columns = table.get("columns", [])
            
            sql_parts.append(f"-- Table: {table_name}")
            sql_parts.append(f"CREATE TABLE IF NOT EXISTS {table_name} (")
            
            column_defs = []
            for col in columns:
                col_name = col.get("name", "column")
                col_type = col.get("type", "TEXT")
                constraints = " ".join(col.get("constraints", []))
                
                col_def = f"    {col_name} {col_type}"
                if constraints:
                    col_def += f" {constraints}"
                column_defs.append(col_def)
            
            sql_parts.append(",\n".join(column_defs))
            sql_parts.append(");")
            sql_parts.append("")
        
        indexes = schema_data.get("indexes", [])
        if indexes:
            sql_parts.append("-- Indexes")
            for idx in indexes:
                table = idx.get("table", "")
                columns = ", ".join(idx.get("columns", []))
                idx_name = f"idx_{table}_{'_'.join(idx.get('columns', []))}"
                sql_parts.append(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({columns});")
            sql_parts.append("")
        
        return "\n".join(sql_parts)