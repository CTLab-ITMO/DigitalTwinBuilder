import random
import time
import threading
import queue
from .base_sensor import BaseSensor

class RFIDReader(BaseSensor):
    def __init__(self, scan_rate=10, read_probability=0.7, zone_size=5, tag_length=12):
        super().__init__()
        self.scan_rate = scan_rate
        self.read_probability = read_probability
        self.zone_size = zone_size
        self.tag_length = tag_length
        self.is_running = False
        self.data_queue = queue.Queue()
        self.tags_in_zone = set()

    def _generate_tag(self):
        return ''.join(random.choice('0123456789ABCDEF') for _ in range(self.tag_length))

    def _manage_zone(self):
        while self.is_running:
            if len(self.tags_in_zone) < self.zone_size:
                self.tags_in_zone.add(self._generate_tag())
            elif len(self.tags_in_zone) > self.zone_size:
                self.tags_in_zone.pop()
            if random.random() < 0.2:
                if random.random() < 0.5 and self.tags_in_zone:
                    self.tags_in_zone.pop()
                else:
                    self.tags_in_zone.add(self._generate_tag())
            time.sleep(0.1)

    def _simulate_scan(self):
        scan_interval = 1.0 / self.scan_rate
        while self.is_running:
            for tag in list(self.tags_in_zone):
                if random.random() < self.read_probability:
                    self.data_queue.put(tag)
            time.sleep(scan_interval)

    def read_value(self):
        if not self.data_queue.empty():
            return self.data_queue.get()
        return None

    def start_scanning(self):
        if not self.is_running:
            self.is_running = True
            self.zone_thread = threading.Thread(target=self._manage_zone, daemon=True)
            self.scan_thread = threading.Thread(target=self._simulate_scan, daemon=True)
            self.zone_thread.start()
            self.scan_thread.start()

    def cleanup(self):
        self.is_running = False
        if hasattr(self, 'zone_thread'):
            self.zone_thread.join()
        if hasattr(self, 'scan_thread'):
            self.scan_thread.join()
        super().cleanup()
