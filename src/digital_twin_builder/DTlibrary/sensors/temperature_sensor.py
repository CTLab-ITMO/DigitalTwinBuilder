from .base_sensor import BaseSensor
import random
import math

class TemperatureSensor(BaseSensor):
    def __init__(self, base_temp=25, target_temp=35, time_constant=50, random_range=0.3):
        super().__init__()
        self.base_temp = base_temp
        self.target_temp = target_temp
        self.time_constant = time_constant
        self.random_range = random_range
        self.measurement_count = 0

    def read_value(self):
        temp_diff = self.target_temp - self.base_temp
        temp = self.base_temp + temp_diff * (1 - math.exp(-self.measurement_count / self.time_constant))
        temp += random.uniform(-self.random_range, self.random_range)
        self.measurement_count += 1
        return temp

    def reset_count(self):
        self.measurement_count = 0

class OrangePiTemperatureSensor(BaseSensor):
    def __init__(self, pin=7, base_temp=25, temp_range=5, noise_level=0.5):
        super().__init__(pin)
        self.base_temp = base_temp
        self.temp_range = temp_range
        self.noise_level = noise_level
    
    def read_value(self):
        try:
            # Simulate reading from actual sensor
            temp = self.base_temp + random.uniform(-self.temp_range, self.temp_range)
            temp += random.gauss(0, self.noise_level)
            return temp
        except Exception as e:
            print(f"Error reading temperature data: {e}")
            return None