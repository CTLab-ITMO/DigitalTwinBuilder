import random
import time
import threading
import queue

class SimulatedRFIDReader:
    def __init__(self, scan_rate=10, read_probability=0.7, zone_size=5, tag_length=12):
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
                if random.random() < 0.5:
                   if len(self.tags_in_zone) > 0 :
                       self.tags_in_zone.pop() 
                else:
                    self.tags_in_zone.add(self._generate_tag())  
            time.sleep(0.1)  

    def _simulate_scan(self):
        scan_interval = 1.0 / self.scan_rate  
        while self.is_running:
            for tag in list(self.tags_in_zone): 
                if random.random() < self.read_probability:
                    print(f"Simulated scan: Tag detected - {tag}")
                    self.data_queue.put(tag)
            time.sleep(scan_interval)

    def start_scanning(self):
        if not self.is_running:
            self.is_running = True
            self.scan_thread = threading.Thread(target=self._simulate_scan, daemon=True)  # daemon=True для автозавершения
            self.zone_thread = threading.Thread(target=self._manage_zone, daemon=True)
            self.scan_thread.start()
            self.zone_thread.start()
            print("RFID simulator started scanning...")

    def stop_scanning(self):
        if self.is_running:
            self.is_running = False
            print("RFID simulator stopped.")

    def read_data(self):
        if not self.data_queue.empty():
            return self.data_queue.get()
        else:
            return None

    def is_active(self):
        return self.is_running


reader = SimulatedRFIDReader(scan_rate=20, read_probability=0.6, zone_size=3, tag_length=8)  
reader.start_scanning()  

try:
    while True:
        time.sleep(0.05) 
        tag = reader.read_data()
        if tag:
            print(f"Read tag from queue: {tag}")

except KeyboardInterrupt:
    print("Shutting down...")
finally:
    reader.stop_scanning() 