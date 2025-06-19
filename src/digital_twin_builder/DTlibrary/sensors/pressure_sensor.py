from .base_sensor import BaseSensor
import random
import math

class PressureSensor(BaseSensor):
    def __init__(self, base_pressure=100, pressure_change_rate=2, noise_level=0.5):
        super().__init__()
        self.base_pressure = base_pressure
        self.pressure_change_rate = pressure_change_rate
        self.noise_level = noise_level
    
    def read_value(self):
        time_now = self.get_time_elapsed()
        pressure = self.base_pressure + self.pressure_change_rate * time_now
        pressure += 5 * math.sin(2 * math.pi * 0.1 * time_now)
        pressure += random.gauss(0, self.noise_level)
        return pressure

class OrangePiPressureSensor(BaseSensor):
    def __init__(self, pin=7):
        super().__init__(pin)
    
    def read_value(self):
        try:
            time_now = self.get_time_elapsed()
            # Simulate reading from actual sensor
            pressure = 100 + 2 * time_now + random.gauss(0, 0.5)
            return pressure
        except Exception as e:
            print(f"Error reading pressure data: {e}")
            return None