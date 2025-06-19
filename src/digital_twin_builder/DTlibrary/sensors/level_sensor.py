from .base_sensor import BaseSensor
import random
import math

class LevelSensor(BaseSensor):
    def __init__(self, base_level=0.5, level_change_rate=0.02, noise_level=0.01):
        super().__init__()
        self.base_level = base_level
        self.level_change_rate = level_change_rate
        self.noise_level = noise_level
    
    def read_value(self):
        time_now = self.get_time_elapsed()
        level = self.base_level + self.level_change_rate * time_now
        level += 0.02 * math.sin(2 * math.pi * 0.2 * time_now)
        level += random.gauss(0, self.noise_level)
        return level  

class OrangePiLevelSensor(BaseSensor):
    def __init__(self, pin=7):
        super().__init__(pin)
    
    def read_value(self):
        try:
            time_now = self.get_time_elapsed()
            # Simulate reading from actual sensor
            level = 0.4 + 0.1 * time_now + random.gauss(0, 0.01)
            return level
        except Exception as e:
            print(f"Error reading level data: {e}")
            return None