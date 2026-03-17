import os
import sys
import math
import numpy as np
import datetime
import time
from collections import defaultdict

# Add PyChrono path if needed
# sys.path.append('/path/to/pychrono')

import pychrono as chrono
import pychrono.irrlicht as irr
import pychrono.fea as fea

class CementPlantDigitalTwin:
    def __init__(self):
        # Initialize Chrono system
        self.system = chrono.ChSystemNSC()
        self.system.Set_G_acc(chrono.ChVectorD(0, -9.81, 0))
        
        # Plant metadata
        self.plant_id = 1
        self.plant_name = "Цементное производство"
        self.location = "Урал"
        self.version = 1
        
        # Sensor metadata
        self.sensors = {}
        self.sensor_ids = {}
        self.setup_sensors()
        
        # Simulation time tracking
        self.start_time = datetime.datetime.now()
        self.current_time = self.start_time
        
        # Data storage
        self.data_log = []
        
        # Equipment objects
        self.equipment = {}
        
        # Configuration settings
        self.config = {
            'temperature_furnace': 1465,
            'pressure_cyclones': 1000,
            'grindiness': 85,
            'gas_composition': {'CO': 0.05, 'NOx': 0.02},
            'mill_loading': 60
        }

    def setup_sensors(self):
        """Initialize sensor metadata"""
        sensor_types = [
            ("температура в печи", "furnace_temperature"),
            ("разрежение в циклонах", "cyclone_pressure"),
            ("тонкость помола", "grindiness"),
            ("состав отходящих газов (CO, NOx)", "gas_composition"),
            ("уровень загрузки мельницы", "mill_loading")
        ]
        
        for i, (name, type_name) in enumerate(sensor_types):
            sensor_id = i + 1
            self.sensors[sensor_id] = {
                'name': name,
                'type': type_name,
                'location': self.get_sensor_location(type_name)
            }
            self.sensor_ids[type_name] = sensor_id
            
    def get_sensor_location(self, sensor_type):
        """Return location of sensor based on its type"""
        locations = {
            'furnace_temperature': 'вращающаяся печь',
            'cyclone_pressure': 'циклон',
            'grindiness': 'сырьевая мельница',
            'gas_composition': 'отходящие газы',
            'mill_loading': 'цементная мельница'
        }
        return locations.get(sensor_type, 'неизвестно')
    
    def create_equipment(self):
        """Create physical representations of cement plant equipment"""
        # Create base ground
        ground = chrono.ChBodyEasyBox(20, 1, 20, 1000, True, True)
        ground.SetPos(chrono.ChVectorD(0, -0.5, 0))
        ground.SetBodyFixed(True)
        self.system.Add(ground)
        
        # Create furnace (rotating kiln)
        furnace_radius = 1.5
        furnace_length = 10
        furnace_body = chrono.ChBodyEasyCylinder(furnace_radius, furnace_length, 2000, True, True)
        furnace_body.SetPos(chrono.ChVectorD(0, 2, 0))
        furnace_body.SetRot(chrono.Q_from_AngAxis(math.pi/2, chrono.ChVectorD(0, 1, 0)))
        self.system.Add(furnce_body)
        self.equipment['furnace'] = furnace_body
        
        # Create raw mill
        mill_radius = 2.0
        mill_length = 5.0
        mill_body = chrono.ChBodyEasyCylinder(mill_radius, mill_length, 1500, True, True)
        mill_body.SetPos(chrono.ChVectorD(0, 5, 0))
        mill_body.SetRot(chrono.Q_from_AngAxis(math.pi/2, chrono.ChVectorD(0, 1, 0)))
        self.system.Add(mill_body)
        self.equipment['raw_mill'] = mill_body
        
        # Create cement mill
        cement_mill_radius = 1.8
        cement_mill_length = 4.0
        cement_mill_body = chrono.ChBodyEasyCylinder(cement_mill_radius, cement_mill_length, 1800, True, True)
        cement_mill_body.SetPos(chrono.ChVectorD(0, 8, 0))
        cement_mill_body.SetRot(chrono.Q_from_AngAxis(math.pi/2, chrono.ChVectorD(0, 1, 0)))
        self.system.Add(cement_mill_body)
        self.equipment['cement_mill'] = cement_mill_body
        
        # Create cooler
        cooler_length = 8
        cooler_width = 2
        cooler_height = 1
        cooler_body = chrono.ChBodyEasyBox(cooler_length, cooler_height, cooler_width, 1200, True, True)
        cooler_body.SetPos(chrono.ChVectorD(0, 10, 0))
        self.system.Add(cooler_body)
        self.equipment['cooler'] = cooler_body
        
        # Create silos
        silo_height = 15
        silo_radius = 1.5
        silo1 = chrono.ChBodyEasyCylinder(silo_radius, silo_height, 1000, True, True)
        silo1.SetPos(chrono.ChVectorD(-5, 15, 0))
        self.system.Add(silo1)
        self.equipment['silo1'] = silo1
        
        silo2 = chrono.ChBodyEasyCylinder(silo_radius, silo_height, 1000, True, True)
        silo2.SetPos(chrono.ChVectorD(5, 15, 0))
        self.system.Add(silo2)
        self.equipment['silo2'] = silo2
    
    def simulate_step(self, step_time):
        """Run one simulation step"""
        # Update time
        self.current_time += datetime.timedelta(seconds=step_time)
        
        # Step the system
        self.system.DoStepDynamics(step_time)
        
        # Collect sensor data
        self.collect_sensor_data()
        
        # Log data
        self.log_data()
        
        return True
    
    def collect_sensor_data(self):
        """Collect data from simulated sensors"""
        # Simulate temperature measurement
        temp = self.config['temperature_furnace'] + np.random.normal(0, 5)
        self.log_sensor_reading('furnace_temperature', temp)
        
        # Simulate pressure measurement
        pressure = self.config['pressure_cyclones'] + np.random.normal(0, 10)
        self.log_sensor_reading('cyclone_pressure', pressure)
        
        # Simulate grindiness measurement
        grindiness = self.config['grindiness'] + np.random.normal(0, 2)
        self.log_sensor_reading('grindiness', grindiness)
        
        # Simulate gas composition
        gas_co = self.config['gas_composition']['CO'] + np.random.normal(0, 0.01)
        gas_nox = self.config['gas_composition']['NOx'] + np.random.normal(0, 0.005)
        self.log_sensor_reading('gas_composition', {'CO': gas_co, 'NOx': gas_nox})
        
        # Simulate mill loading
        mill_load = self.config['mill_loading'] + np.random.normal(0, 3)
        self.log_sensor_reading('mill_loading', mill_load)
    
    def log_sensor_reading(self, sensor_type, value):
        """Log a single sensor reading"""
        sensor_id = self.sensor_ids.get(sensor_type)
        if sensor_id:
            self.data_log.append({
                'timestamp': self.current_time,
                'sensor_id': sensor_id,
                'value': value,
                'plant_id': self.plant_id
            })
    
    def log_data(self):
        """Log all collected data according to database schema"""
        print(f"Logging {len(self.data_log)} records at {self.current_time}")
        # In a real implementation, this would write to database
        # For now, we just print to console
        for record in self.data_log:
            sensor_name = self.sensors[record['sensor_id']]['name']
            print(f"Sensor: {sensor_name}, Value: {record['value']}, Time: {record['timestamp']}")
        self.data_log.clear()

def run_simulation():
    """Main simulation function"""
    # Create digital twin instance
    twin = CementPlantDigitalTwin()
    
    # Setup equipment
    twin.create_equipment()
    
    # Run simulation for 100 seconds with 0.1 second steps
    dt = 0.1
    total_time = 100.0
    steps = int(total_time / dt)
    
    print("Starting cement plant digital twin simulation...")
    print(f"Total simulation time: {total_time} seconds")
    print(f"Time step: {dt} seconds")
    print(f"Number of steps: {steps}")
    
    try:
        for i in range(steps):
            twin.simulate_step(dt)
            
            # Print progress every 10 steps
            if i % 10 == 0:
                print(f"Progress: {i}/{steps} steps completed")
                
    except KeyboardInterrupt:
        print("\nSimulation interrupted by user")
    except Exception as e:
        print(f"Error during simulation: {str(e)}")
    finally:
        print("Simulation finished")
        print(f"Final time: {twin.current_time}")

if __name__ == "__main__":
    run_simulation()