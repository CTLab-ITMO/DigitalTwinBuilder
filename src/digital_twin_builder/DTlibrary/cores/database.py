import psycopg2
from psycopg2 import sql
import logging
from typing import Dict, Any

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
                unit VARCHAR(10),
                tag_id VARCHAR(20))""",
            """CREATE INDEX IF NOT EXISTS idx_sensor_timestamp 
               ON sensor_data (timestamp)""",
            """CREATE INDEX IF NOT EXISTS idx_sensor_type 
               ON sensor_data (sensor_type)"""
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
            timestamp = data["timestamp"]
            for sensor_type, value in data["sensor_data"].items():
                if sensor_type == "rfid":
                    query = """INSERT INTO sensor_data 
                              (timestamp, sensor_type, tag_id) 
                              VALUES (%s, %s, %s)"""
                    params = (timestamp, sensor_type, value)
                else:
                    query = """INSERT INTO sensor_data 
                              (timestamp, sensor_type, value) 
                              VALUES (%s, %s, %s)"""
                    params = (timestamp, sensor_type, value)
                
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