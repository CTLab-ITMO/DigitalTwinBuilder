import pychrono.core as chrono
import pychrono.irrlicht as chronoirr
import pychrono.vehicle as veh
import numpy as np
import time
import threading
import queue
import json
import logging
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor
import math
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CementPlantDigitalTwin:
    def __init__(self):
        self.system = chrono.ChSystemNSC()
        self.system.Set_G_acc(chrono.ChVectorD(0, -9.81, 0))
        
        self.application = None
        self.bodies = {}
        self.sensors = {}
        self.data_queue = queue.Queue()
        self.simulation_running = False
        
        self.db_config = {
            'host': 'localhost',
            'database': 'cement_plant',
            'user': 'postgres',
            'password': 'password'
        }
        
        self.plant_id = 1
        self.sensor_configs = {
            'kiln_temperature': {'id': 1, 'type': 'temperature', 'location': 'rotary_kiln'},
            'cyclone_vacuum': {'id': 2, 'type': 'pressure', 'location': 'cyclone'},
            'grinding_fineness': {'id': 3, 'type': 'particle_size', 'location': 'cement_mill'},
            'co_emission': {'id': 4, 'type': 'gas_composition', 'location': 'exhaust_stack'},
            'nox_emission': {'id': 5, 'type': 'gas_composition', 'location': 'exhaust_stack'},
            'mill_load': {'id': 6, 'type': 'load', 'location': 'raw_mill'}
        }
        
        self.critical_params = {
            'sintering_temp_min': 1450,
            'sintering_temp_max': 1480,
            'free_lime_max': 1.5,
            'co_emission_max': 0.1
        }
        
    def initialize_database(self):
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO metadata (plant_name, location, version, last_updated)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id;
            """, ('Cement Plant Digital Twin', 'Main Facility', 1, datetime.now(timezone.utc)))
            
            result = cursor.fetchone()
            if result:
                self.plant_id = result[0]
            
            for sensor_name, config in self.sensor_configs.items():
                cursor.execute("""
                    INSERT INTO sensor_metadata (sensor_type, location, calibration_status, sensor_id)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (sensor_id) DO NOTHING;
                """, (config['type'], config['location'], True, config['id']))
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
    
    def create_materials(self):
        self.materials = {}
        
        steel_mat = chrono.ChMaterialSurfaceNSC()
        steel_mat.SetFriction(0.7)
        steel_mat.SetRestitution(0.2)
        steel_mat.SetYoungModulus(2e11)
        steel_mat.SetPoissonRatio(0.3)
        self.materials['steel'] = steel_mat
        
        refractory_mat = chrono.ChMaterialSurfaceNSC()
        refractory_mat.SetFriction(0.8)
        refractory_mat.SetRestitution(0.1)
        refractory_mat.SetYoungModulus(5e10)
        refractory_mat.SetPoissonRatio(0.25)
        self.materials['refractory'] = refractory_mat
        
        concrete_mat = chrono.ChMaterialSurfaceNSC()
        concrete_mat.SetFriction(0.6)
        concrete_mat.SetRestitution(0.1)
        concrete_mat.SetYoungModulus(3e10)
        concrete_mat.SetPoissonRatio(0.2)
        self.materials['concrete'] = concrete_mat
        
    def create_crusher(self):
        crusher_body = chrono.ChBodyEasyBox(3, 2, 2, 8000, True, True, self.materials['steel'])
        crusher_body.SetPos(chrono.ChVectorD(-20, 1, 0))
        crusher_body.SetBodyFixed(True)
        self.system.Add(crusher_body)
        self.bodies['crusher'] = crusher_body
        
        jaw_body = chrono.ChBodyEasyBox(0.5, 1.5, 1.8, 2000, True, True, self.materials['steel'])
        jaw_body.SetPos(chrono.ChVectorD(-19, 1, 0))
        self.system.Add(jaw_body)
        self.bodies['crusher_jaw'] = jaw_body
        
        jaw_motor = chrono.ChLinkMotorRotationSpeed()
        jaw_motor.Initialize(jaw_body, crusher_body, chrono.ChFrameD(chrono.ChVectorD(-19, 1, 0)))
        jaw_motor.SetSpeedFunction(chrono.ChFunction_Const(0.5))
        self.system.Add(jaw_motor)
        
    def create_raw_mill(self):
        mill_body = chrono.ChBodyEasyCylinder(2, 8, 12000, True, True, self.materials['steel'])
        mill_body.SetPos(chrono.ChVectorD(-10, 2, 0))
        mill_body.SetRot(chrono.Q_from_AngX(chrono.CH_C_PI_2))
        self.system.Add(mill_body)
        self.bodies['raw_mill'] = mill_body
        
        mill_motor = chrono.ChLinkMotorRotationSpeed()
        mill_motor.Initialize(mill_body, chrono.ChBodyEasyBox(0.1, 0.1, 0.1, 1, False, False), 
                             chrono.ChFrameD(chrono.ChVectorD(-10, 2, 0)))
        mill_motor.SetSpeedFunction(chrono.ChFunction_Const(1.2))
        self.system.Add(mill_motor)
        
        for i in range(20):
            ball = chrono.ChBodyEasySphere(0.1, 500, True, True, self.materials['steel'])
            ball.SetPos(chrono.ChVectorD(-10 + random.uniform(-3.5, 3.5), 
                                       2 + random.uniform(-1.8, 1.8),
                                       random.uniform(-1.8, 1.8)))
            self.system.Add(ball)
            
    def create_rotary_kiln(self):
        kiln_body = chrono.ChBodyEasyCylinder(2.5, 25, 50000, True, True, self.materials['refractory'])
        kiln_body.SetPos(chrono.ChVectorD(10, 3, 0))
        kiln_body.SetRot(chrono.Q_from_AngZ(0.05))
        self.system.Add(kiln_body)
        self.bodies['rotary_kiln'] = kiln_body
        
        kiln_motor = chrono.ChLinkMotorRotationSpeed()
        kiln_motor.Initialize(kiln_body, chrono.ChBodyEasyBox(0.1, 0.1, 0.1, 1, False, False),
                             chrono.ChFrameD(chrono.ChVectorD(10, 3, 0)))
        kiln_motor.SetSpeedFunction(chrono.ChFunction_Const(0.2))
        self.system.Add(kiln_motor)
        
        support1 = chrono.ChBodyEasyCylinder(0.3, 1, 2000, True, True, self.materials['steel'])
        support1.SetPos(chrono.ChVectorD(5, 0.5, 0))
        support1.SetBodyFixed(True)
        self.system.Add(support1)
        
        support2 = chrono.ChBodyEasyCylinder(0.3, 1, 2000, True, True, self.materials['steel'])
        support2.SetPos(chrono.ChVectorD(15, 0.5, 0))
        support2.SetBodyFixed(True)
        self.system.Add(support2)
        
    def create_grate_cooler(self):
        cooler_body = chrono.ChBodyEasyBox(8, 1, 4, 15000, True, True, self.materials['steel'])
        cooler_body.SetPos(chrono.ChVectorD(25, 0.5, 0))
        cooler_body.SetBodyFixed(True)
        self.system.Add(cooler_body)
        self.bodies['grate_cooler'] = cooler_body
        
        for i in range(10):
            grate = chrono.ChBodyEasyBox(0.8, 0.1, 3.8, 200, True, True, self.materials['steel'])
            grate.SetPos(chrono.ChVectorD(21 + i * 0.8, 1.1, 0))
            self.system.Add(grate)
            
            grate_motor = chrono.ChLinkMotorLinearSpeed()
            grate_motor.Initialize(grate, cooler_body, 
                                 chrono.ChFrameD(chrono.ChVectorD(21 + i * 0.8, 1.1, 0)))
            grate_motor.SetSpeedFunction(chrono.ChFunction_Sine(0, 0.1, 0.5))
            self.system.Add(grate_motor)
    
    def create_cement_mill(self):
        cement_mill_body = chrono.ChBodyEasyCylinder(1.8, 6, 8000, True, True, self.materials['steel'])
        cement_mill_body.SetPos(chrono.ChVectorD(35, 1.8, 0))
        cement_mill_body.SetRot(chrono.Q_from_AngX(chrono.CH_C_PI_2))
        self.system.Add(cement_mill_body)
        self.bodies['cement_mill'] = cement_mill_body
        
        cement_mill_motor = chrono.ChLinkMotorRotationSpeed()
        cement_mill_motor.Initialize(cement_mill_body, chrono.ChBodyEasyBox(0.1, 0.1, 0.1, 1, False, False),
                                   chrono.ChFrameD(chrono.ChVectorD(35, 1.8, 0)))
        cement_mill_motor.SetSpeedFunction(chrono.ChFunction_Const(1.5))
        self.system.Add(cement_mill_motor)
        
    def create_silos(self):
        for i in range(3):
            silo = chrono.ChBodyEasyCylinder(2, 8, 5000, True, True, self.materials['concrete'])
            silo.SetPos(chrono.ChVectorD(45 + i * 5, 4, 0))
            silo.SetBodyFixed(True)
            self.system.Add(silo)
            self.bodies[f'silo_{i+1}'] = silo
            
    def create_sensors(self):
        self.sensors['kiln_temperature'] = KilnTemperatureSensor(self.bodies.get('rotary_kiln'))
        self.sensors['cyclone_vacuum'] = CycloneVacuumSensor()
        self.sensors['grinding_fineness'] = GrindingFinenessSensor(self.bodies.get('cement_mill'))
        self.sensors['co_emission'] = COEmissionSensor(self.bodies.get('rotary_kiln'))
        self.sensors['nox_emission'] = NOxEmissionSensor(self.bodies.get('rotary_kiln'))
        self.sensors['mill_load'] = MillLoadSensor(self.bodies.get('raw_mill'))
        
    def setup_visualization(self):
        self.application = chronoirr.ChIrrApp(self.system, "Cement Plant Digital Twin", 
                                            chronoirr.dimension2du(1024, 768))
        self.application.AddTypicalSky()
        self.application.AddTypicalLights()
        self.application.AddTypicalCamera(chronoirr.vector3df(0, 10, -30))
        self.application.AssetBindAll()
        self.application.AssetUpdateAll()
        
    def log_sensor_data(self, sensor_name, value):
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            sensor_id = self.sensor_configs[sensor_name]['id']
            
            cursor.execute("""
                INSERT INTO plant_data (timestamp, value, sensor_id, plant_id)
                VALUES (%s, %s, %s, %s);
            """, (datetime.now(timezone.utc), value, sensor_id, self.plant_id))
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to log sensor data for {sensor_name}: {e}")
            
    def check_critical_parameters(self, sensor_readings):
        alerts = []
        
        if 'kiln_temperature' in sensor_readings:
            temp = sensor_readings['kiln_temperature']
            if temp < self.critical_params['sintering_temp_min']:
                alerts.append(f"Kiln temperature too low: {temp}°C")
            elif temp > self.critical_params['sintering_temp_max']:
                alerts.append(f"Kiln temperature too high: {temp}°C")
                
        if 'co_emission' in sensor_readings:
            co = sensor_readings['co_emission']
            if co > self.critical_params['co_emission_max']:
                alerts.append(f"CO emission exceeds limit: {co}%")
                
        return alerts
        
    def data_collection_thread(self):
        while self.simulation_running:
            try:
                sensor_readings = {}
                for sensor_name, sensor in self.sensors.items():
                    value = sensor.read()
                    sensor_readings[sensor_name] = value
                    self.log_sensor_data(sensor_name, value)
                    
                alerts = self.check_critical_parameters(sensor_readings)
                if alerts:
                    for alert in alerts:
                        logger.warning(alert)
                        
                logger.info(f"Sensor readings: {sensor_readings}")
                time.sleep(10)
                
            except Exception as e:
                logger.error(f"Error in data collection thread: {e}")
                time.sleep(5)
                
    def run_simulation(self, duration=3600):
        try:
            self.initialize_database()
            self.create_materials()
            self.create_crusher()
            self.create_raw_mill()
            self.create_rotary_kiln()
            self.create_grate_cooler()
            self.create_cement_mill()
            self.create_silos()
            self.create_sensors()
            
            self.simulation_running = True
            data_thread = threading.Thread(target=self.data_collection_thread)
            data_thread.daemon = True
            data_thread.start()
            
            if self.application:
                self.setup_visualization()
                
            self.system.SetTimestepperType(chrono.ChTimestepper.Type_EULER_IMPLICIT_PROJECTED)
            self.system.SetSolverType(chrono.ChSolver.Type_PSOR)
            self.system.SetMaxItersSolverSpeed(50)
            
            timestep = 0.01
            simulation_time = 0
            
            logger.info("Starting cement plant simulation...")
            
            if self.application:
                self.application.SetTimestep(timestep)
                while self.application.GetDevice().run() and simulation_time < duration:
                    self.application.BeginScene()
                    self.application.DrawAll()
                    self.application.DoStep()
                    self.application.EndScene()
                    simulation_time += timestep
            else:
                while simulation_time < duration:
                    self.system.DoStepDynamics(timestep)
                    simulation_time += timestep
                    
                    if int(simulation_time) % 60 == 0:
                        logger.info(f"Simulation time: {int(simulation_time/60)} minutes")
                        
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            raise
        finally:
            self.simulation_running = False
            logger.info("Simulation completed")

class BaseSensor:
    def __init__(self):
        self.last_reading = 0
        self.noise_factor = 0.02
        
    def add_noise(self, value):
        noise = random.gauss(0, abs(value) * self.noise_factor)
        return value + noise

class KilnTemperatureSensor(BaseSensor):
    def __init__(self, kiln_body):
        super().__init__()
        self.kiln_body = kiln_body
        self.base_temperature = 1465
        
    def read(self):
        if self.kiln_body:
            angular_vel = self.kiln_body.GetWvel_loc().Length()
            temp_variation = math.sin(time.time() * 0.1) * 15
            fuel_efficiency = 0.95 + random.uniform(-0.05, 0.05)
            temperature = self.base_temperature + temp_variation * fuel_efficiency
            return self.add_noise(temperature)
        return self.add_noise(self.base_temperature)

class CycloneVacuumSensor(BaseSensor):
    def __init__(self):
        super().__init__()
        self.base_vacuum = -2500
        
    def read(self):
        variation = math.sin(time.time() * 0.2) * 200
        vacuum = self.base_vacuum + variation
        return self.add_noise(vacuum)

class GrindingFinenessSensor(BaseSensor):
    def __init__(self, mill_body):
        super().__init__()
        self.mill_body = mill_body
        self.target_fineness = 320
        
    def read(self):
        if self.mill_body:
            angular_vel = self.mill_body.GetWvel_loc().Length()
            efficiency = min(1.0, angular_vel / 2.0)
            fineness = self.target_fineness * (0.8 + 0.4 * efficiency)
            return self.add_noise(fineness)
        return self.add_noise(self.target_fineness)

class COEmissionSensor(BaseSensor):
    def __init__(self, kiln_body):
        super().__init__()
        self.kiln_body = kiln_body
        self.base_emission = 0.05
        
    def read(self):
        combustion_efficiency = 0.98 + random.uniform(-0.03, 0.02)
        emission = self.base_emission * (2 - combustion_efficiency)
        return max(0, self.add_noise(emission))

class NOxEmissionSensor(BaseSensor):
    def __init__(self, kiln_body):
        super().__init__()
        self.kiln_body = kiln_body
        self.base_emission = 450
        
    def read(self):
        temp_factor = 1 + math.sin(time.time() * 0.1) * 0.1
        emission = self.base_emission * temp_factor
        return max(0, self.add_noise(emission))

class MillLoadSensor(BaseSensor):
    def __init__(self, mill_body):
        super().__init__()
        self.mill_body = mill_body
        self.rated_load = 85
        
    def read(self):
        load_variation = math.sin(time.time() * 0.05) * 10
        current_load = self.rated_load + load_variation
        return max(0, min(100, self.add_noise(current_load)))

if __name__ == "__main__":
    try:
        cement_plant = CementPlantDigitalTwin()
        cement_plant.run_simulation(duration=7200)
    except KeyboardInterrupt:
        logger.info("Simulation interrupted by user")
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        raise