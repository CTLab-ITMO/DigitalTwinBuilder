import logging
from typing import Dict, Any
import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta
import random
import json

class DatabaseManager:
    def __init__(self, dbname, user, password, host="localhost", port="5432"):
        self.conn_params = {
            "dbname": dbname, "user": user, "password": password,
            "host": host, "port": port
        }
        self.logger = logging.getLogger("DatabaseManager")
        self._connect()

    def _connect(self):
        try:
            self.conn = psycopg2.connect(**self.conn_params)
            self.cursor = self.conn.cursor()
            self.logger.info("Connected to PostgreSQL database")
        except Exception as e:
            self.logger.error(f"Database connection failed: {e}")
            raise

    def create_sensor_tables(self):
        """Create tables for all sensor types"""
        queries = [
            """CREATE TABLE IF NOT EXISTS sensor_data (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                sensor_type VARCHAR(20) NOT NULL,
                value FLOAT,
                string_value VARCHAR(50),
                unit VARCHAR(10),
                tag_id VARCHAR(20)
            )""",
            """CREATE TABLE IF NOT EXISTS steel_melting_data (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                furnace_id VARCHAR(20),
                temperature FLOAT,
                power_consumption FLOAT,
                vibration_level FLOAT,
                chemical_composition JSON
            )""",
            """CREATE TABLE IF NOT EXISTS equipment_status (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                equipment_type VARCHAR(50),
                status VARCHAR(20),
                wear_level FLOAT,
                maintenance_due DATE
            )""",
            """CREATE TABLE IF NOT EXISTS production_quality (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                batch_id VARCHAR(30),
                steel_grade VARCHAR(20),
                defect_count INTEGER,
                quality_score FLOAT
            )""",
            """CREATE INDEX IF NOT EXISTS idx_steel_timestamp ON steel_melting_data (timestamp)""",
            """CREATE INDEX IF NOT EXISTS idx_equipment_timestamp ON equipment_status (timestamp)""",
            """CREATE INDEX IF NOT EXISTS idx_quality_timestamp ON production_quality (timestamp)"""
        ]
        try:
            for query in queries:
                self.cursor.execute(query)
            self.conn.commit()
            self.logger.info("Sensor tables created successfully")
        except Exception as e:
            self.conn.rollback()
            self.logger.error(f"Table creation failed: {e}")
            raise

    def store_sensor_data(self, data: Dict[str, Any]):
        """Store sensor data in the database"""
        try:
            timestamp = datetime.fromtimestamp(data["timestamp"])
            for sensor_type, value in data["sensor_data"].items():
                if sensor_type in ["status", "equipment_status", "steel_grade", "rfid"]:
                    query = """INSERT INTO sensor_data (timestamp, sensor_type, tag_id) VALUES (%s, %s, %s)"""
                    params = (timestamp, sensor_type, str(value))
                else:
                    query = """INSERT INTO sensor_data (timestamp, sensor_type, value) VALUES (%s, %s, %s)"""
                    params = (timestamp, sensor_type, float(value))
                self.cursor.execute(query, params)
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            self.logger.error(f"Data storage failed: {e}")
            raise

    def close(self):
        self.cursor.close()
        self.conn.close()
        self.logger.info("Database connection closed")

    def generate_test_data(self, days=7, records_per_day=100):
        """Generate test data for demonstration purposes"""
        self.logger.info("Generating test data...")
        base_time = datetime.now() - timedelta(days=days) 
        try:
            for i in range(days * records_per_day):
                timestamp = base_time + timedelta(
                    days=i//records_per_day,
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                    seconds=random.randint(0, 59)
                )
                furnace_id = f"F{random.randint(1, 3)}"
                temperature = random.uniform(1500, 1600)
                power_consumption = random.uniform(1000, 2000)
                vibration_level = random.uniform(0.5, 5.0)
                chemical_composition = json.dumps({
                    "C": round(random.uniform(0.1, 0.3), 3),
                    "Si": round(random.uniform(0.15, 0.35), 3),
                    "Mn": round(random.uniform(0.5, 1.5), 3),
                    "P": round(random.uniform(0.01, 0.03), 3),
                    "S": round(random.uniform(0.01, 0.03), 3),
                    "Cr": round(random.uniform(17.0, 19.0), 3),
                    "Ni": round(random.uniform(8.0, 10.0), 3)
                })
                query = """INSERT INTO steel_melting_data (timestamp, furnace_id, temperature, power_consumption, vibration_level, chemical_composition) VALUES (%s, %s, %s, %s, %s, %s)"""
                params = (timestamp, furnace_id, temperature, power_consumption, vibration_level, chemical_composition)
                self.cursor.execute(query, params)

            equipment_types = ['crystallizer', 'conveyor', 'cooling_system', 'cutter']
            statuses = ['normal', 'warning', 'critical']
            for i in range(days * 10):
                timestamp = base_time + timedelta(
                    days=i//10,
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                    seconds=random.randint(0, 59)
                )
                equipment_type = random.choice(equipment_types)
                status = random.choice(statuses)
                wear_level = random.uniform(0, 100)
                maintenance_due = timestamp + timedelta(days=random.randint(1, 30))
                query = """INSERT INTO equipment_status (timestamp, equipment_type, status, wear_level, maintenance_due) VALUES (%s, %s, %s, %s, %s)"""
                params = (timestamp, equipment_type, status, wear_level, maintenance_due)
                self.cursor.execute(query, params)

            steel_grades = ['AISI304', 'AISI316', 'AISI321', 'AISI430']
            for i in range(days * 20):
                timestamp = base_time + timedelta(
                    days=i//20,
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                    seconds=random.randint(0, 59)
                )
                batch_id = f"B{1000 + i}"
                steel_grade = random.choice(steel_grades)
                defect_count = random.randint(0, 10)
                quality_score = random.uniform(80, 100)
                query = """INSERT INTO production_quality (timestamp, batch_id, steel_grade, defect_count, quality_score) VALUES (%s, %s, %s, %s, %s)"""
                params = (timestamp, batch_id, steel_grade, defect_count, quality_score)
                self.cursor.execute(query, params)

            self.conn.commit()
            self.logger.info(f"Generated test data for {days} days")
            return True
        except Exception as e:
            self.conn.rollback()
            self.logger.error(f"Test data generation failed: {e}")
            return False
