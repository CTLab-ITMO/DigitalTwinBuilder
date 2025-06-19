import time
import random
import math
from abc import ABC, abstractmethod
try:
    import OPi.GPIO as GPIO
except ImportError:
    print("OPi.GPIO not installed. Using fake GPIO.")
    class FakeGPIO:
        def setmode(self, mode): pass
        def setup(self, pin, mode): pass
        def input(self, pin): return 0
        def output(self, pin, value): pass
        def cleanup(self): pass
    GPIO = FakeGPIO()

class BaseSensor(ABC):
    def __init__(self, pin=None):
        self.pin = pin
        self.start_time = time.time()
        if pin is not None:
            GPIO.setmode(GPIO.BOARD)
            GPIO.setup(self.pin, GPIO.IN)
    
    @abstractmethod
    def read_value(self):
        """Read a sensor value"""
        pass
    
    def cleanup(self):
        """Clean up resources"""
        if self.pin is not None:
            GPIO.cleanup()
    
    def get_time_elapsed(self):
        """Get time since sensor started"""
        return time.time() - self.start_time