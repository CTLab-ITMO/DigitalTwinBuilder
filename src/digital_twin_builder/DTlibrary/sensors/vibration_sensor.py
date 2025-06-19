from .base_sensor import BaseSensor
import random
import math

class VibrationSensor(BaseSensor):
    def __init__(self, base_amplitude=0.1, frequency=1.0, noise_level=0.05, offset=0):
        super().__init__()
        self.base_amplitude = base_amplitude
        self.frequency = frequency
        self.noise_level = noise_level
        self.offset = offset

    def read_value(self):
        time_now = self.get_time_elapsed()
        amplitude = self.base_amplitude * math.sin(2 * math.pi * self.frequency * time_now) + self.offset
        amplitude += random.gauss(0, self.noise_level)
        return amplitude

class OrangePiVibrationSensor(BaseSensor):
    def __init__(self, pin=7):
        super().__init__(pin)
    
    def read_value(self):
        try:
            time_now = self.get_time_elapsed()
            # Simulate reading from actual sensor
            amplitude = 0.1 * math.sin(2 * math.pi * 2 * time_now) + random.gauss(0, 0.05)
            return amplitude
        except Exception as e:
            print(f"Error reading vibration data: {e}")
            return None