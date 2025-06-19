import time
from typing import Dict, Any
from queue import Queue
from threading import Thread
from sensors import (LevelSensor, OrangePiLevelSensor,
                    PressureSensor, OrangePiPressureSensor,
                    RFIDReader,
                    TemperatureSensor, OrangePiTemperatureSensor,
                    VibrationSensor, OrangePiVibrationSensor,
                    WearSensor, OrangePiWearSensor)
import random
import math
from datetime import datetime

class SensorManager:
    def __init__(self, mode='sim'):
        """
        Initialize sensor manager with either simulated or real sensors
        :param mode: 'sim' for simulated sensors, 'real' for OrangePi sensors
        """
        self.mode = mode
        self.sensors = self._initialize_sensors()
        self.data_queue = Queue()
        self.running = False
        self.sampling_interval = 1.0
        self.last_data = {}  

    def _initialize_sensors(self):
        if self.mode == 'sim':
            return {
                "temperature": TemperatureSensor(),
                "pressure": PressureSensor(),
                "vibration": VibrationSensor(),
                "level": LevelSensor(),
                "wear": WearSensor(),
                "rfid": RFIDReader()
            }
        else:
            return {
                "temperature": OrangePiTemperatureSensor(pin=7),
                "pressure": OrangePiPressureSensor(pin=11),
                "vibration": OrangePiVibrationSensor(pin=13),
                "level": OrangePiLevelSensor(pin=15),
                "wear": OrangePiWearSensor(pin=19),
            }

    def start(self):
        self.running = True
        if isinstance(self.sensors["rfid"], (RFIDReader)):
            self.sensors["rfid"].start_scanning()
        self.thread = Thread(target=self._collect_data, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if isinstance(self.sensors["rfid"], (RFIDReader)):
            self.sensors["rfid"].cleanup()
        if hasattr(self, 'thread'):
            self.thread.join()
        for sensor in self.sensors.values():
            if hasattr(sensor, 'cleanup'):
                sensor.cleanup()

    def _collect_data(self):
        while self.running:
            timestamp = time.time()
            sensor_data = {
                "timestamp": timestamp,
                "sensor_data": {}
            }
            
            # Generate realistic metallurgy data
            if self.mode == 'sim':
                # Инициализируем базовые значения
                base_temp = 1520
                base_speed = 1.8
                base_water_flow = 1250
                base_vibration = 3.0
                
                # Если есть предыдущие данные, используем их как основу
                if self.last_data:
                    base_temp = self.last_data.get("temperature", 1520)
                    base_speed = self.last_data.get("casting_speed", 1.8)
                    base_water_flow = self.last_data.get("cooling_water_flow", 1250)
                    base_vibration = self.last_data.get("vibration_level", 3.0)
                
                # Temperature follows a pattern with random fluctuations
                temp_fluctuation = 20 * math.sin(time.time() / 600)  # 10 min cycle
                sensor_data["sensor_data"]["temperature"] = base_temp + temp_fluctuation + random.uniform(-5, 5)
                
                # Casting speed varies around 1.8 m/min
                sensor_data["sensor_data"]["casting_speed"] = base_speed + 0.1 * math.sin(time.time() / 300) + random.uniform(-0.05, 0.05)
                
                # Cooling water flow
                sensor_data["sensor_data"]["cooling_water_flow"] = base_water_flow + 50 * math.sin(time.time() / 450) + random.uniform(-20, 20)
                
                # Vibration level
                sensor_data["sensor_data"]["vibration_level"] = base_vibration + 1.0 * math.sin(time.time() / 180) + random.uniform(-0.2, 0.2)
                
                # Equipment status (changes slowly)
                current_status = self.last_data.get("status", "normal")
                if random.random() < 0.05:  # 5% chance to change status
                    sensor_data["sensor_data"]["status"] = random.choice(["normal", "warning", "critical"])
                else:
                    sensor_data["sensor_data"]["status"] = current_status
                
                # Wear level gradually increases
                current_wear = self.last_data.get("wear_level", 0)
                new_wear = current_wear + 0.001
                sensor_data["sensor_data"]["wear_level"] = min(new_wear, 100)
                
                # Quality metrics (batch-based)
                current_defects = self.last_data.get("defect_count", 0)
                current_quality = self.last_data.get("quality_score", 95)
                
                if time.time() % 300 < self.sampling_interval:  # Every 5 minutes
                    sensor_data["sensor_data"]["defect_count"] = random.randint(0, 5)
                    sensor_data["sensor_data"]["quality_score"] = 95 - sensor_data["sensor_data"]["defect_count"] * 2 + random.uniform(-1, 1)
                else:
                    sensor_data["sensor_data"]["defect_count"] = current_defects
                    sensor_data["sensor_data"]["quality_score"] = current_quality
            
            else:
                pass
            
            self.last_data = sensor_data["sensor_data"].copy()
            self.data_queue.put(sensor_data)
            time.sleep(self.sampling_interval)

    def get_data(self) -> Dict[str, Any]:
        if not self.data_queue.empty():
            return self.data_queue.get()
        return None

    def set_mode(self, mode: str):
        if mode in ['sim', 'real'] and mode != self.mode:
            self.stop()
            self.mode = mode
            self.sensors = self._initialize_sensors()
            if self.running:
                self.start()