from .base_sensor import BaseSensor
import random
import math

class WearSensor(BaseSensor):
    def __init__(self, initial_wear=0.0, wear_rate=0.005, noise_level=0.002):
        super().__init__()
        self.initial_wear = initial_wear
        self.wear_rate = wear_rate
        self.noise_level = noise_level

    def read_value(self):
        time_now = self.get_time_elapsed()
        wear = self.initial_wear + self.wear_rate * time_now
        wear += 0.01 * math.sin(2 * math.pi * 0.05 * time_now)
        wear = min(max(0, wear), 1) 
        wear += random.gauss(0, self.noise_level)
        return wear

class OrangePiWearSensor(BaseSensor):
    def __init__(self, pin=7):
        super().__init__(pin)
    
    def read_value(self):
        try:
            time_now = self.get_time_elapsed()
            # Simulate reading from actual sensor
            wear = 0.1 * time_now + random.gauss(0, 0.002)
            return wear
        except Exception as e:
            print(f"Error reading wear data: {e}")
            return None