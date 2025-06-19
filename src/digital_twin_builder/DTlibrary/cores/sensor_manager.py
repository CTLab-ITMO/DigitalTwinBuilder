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
            
            for name, sensor in self.sensors.items():
                if name != "rfid": 
                    value = sensor.read_value()
                    if value is not None:
                        sensor_data["sensor_data"][name] = value
            
            rfid_tag = self.sensors["rfid"].read_value()
            if rfid_tag:
                sensor_data["sensor_data"]["rfid"] = rfid_tag
            
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