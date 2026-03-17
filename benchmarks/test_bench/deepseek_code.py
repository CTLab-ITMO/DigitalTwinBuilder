import math
import time
import numpy as np
import pychrono as chrono
import pychrono.irrlicht as irrlicht
import psycopg2
from datetime import datetime, timezone
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CementPlantDigitalTwin:
    def __init__(self):
        self.system = chrono.ChSystemNSC()
        self.system.Set_G_acc(chrono.ChVectorD(0, -9.81, 0))
        
        # Database connection parameters
        self.db_params = {
            'dbname': 'cement_plant_db',
            'user': 'postgres',
            'password': 'password',
            'host': 'localhost',
            'port': '5432'
        }
        
        # Sensor data storage
        self.sensor_readings = {
            'temperature': [],
            'pressure': [],
            'fineness': [],
            'co_emission': [],
            'nox_emission': [],
            'mill_load': []
        }
        
        # Critical parameters
        self.critical_params = {
            'sintering_temp': (1450, 1480),
            'free_lime': 1.5,
            'co_emission_limit': 0.1
        }
        
        self.setup_scene()
        self.setup_sensors()
        
    def setup_scene(self):
        # Create ground
        ground = chrono.ChBodyEasyBox(100, 1, 100, 1000, True, True)
        ground.SetBodyFixed(True)
        ground.SetPos(chrono.ChVectorD(0, -0.5, 0))
        ground.GetVisualShape(0).SetTexture(chrono.ChTexture(chrono.GetChronoDataFile('textures/concrete.jpg')))
        self.system.Add(ground)
        
        # Create rotary kiln (main furnace)
        self.create_rotary_kiln()
        
        # Create crusher
        self.create_crusher()
        
        # Create raw mill
        self.create_raw_mill()
        
        # Create cooler
        self.create_cooler()
        
        # Create cement mill
        self.create_cement_mill()
        
        # Create silos
        self.create_silos()
        
    def create_rotary_kiln(self):
        # Kiln body (rotating cylinder)
        kiln_length = 60.0
        kiln_diameter = 4.0
        kiln_body = chrono.ChBodyEasyCylinder(chrono.ChAxis_Y, kiln_diameter/2, kiln_length, 5000, True, True)
        kiln_body.SetPos(chrono.ChVectorD(0, 3, 0))
        kiln_body.SetMass(15000)
        self.system.Add(kiln_body)
        self.kiln_body = kiln_body
        
        # Kiln rotation motor
        motor = chrono.ChLinkMotorRotationSpeed()
        motor.Initialize(kiln_body, ground, chrono.ChFrameD(chrono.ChVectorD(0, 3, 0)))
        motor_speed = chrono.ChFunction_Const(0.5)  # 0.5 RPM
        motor.SetSpeedFunction(motor_speed)
        self.system.Add(motor)
        self.kiln_motor = motor
        
        # Refractory lining (inner layer)
        refractory = chrono.ChBodyEasyCylinder(chrono.ChAxis_Y, kiln_diameter/2 - 0.2, kiln_length - 2, 3000, False, True)
        refractory.SetPos(chrono.ChVectorD(0, 3, 0))
        refractory.GetVisualShape(0).SetColor(chrono.ChColor(0.7, 0.3, 0.1))
        self.system.Add(refractory)
        
        # Fixed link between kiln and refractory
        refractory_link = chrono.ChLinkLockLock()
        refractory_link.Initialize(refractory, kiln_body, chrono.ChCoordsysD(chrono.ChVectorD(0, 3, 0)))
        self.system.Add(refractory_link)
        
    def create_crusher(self):
        crusher_base = chrono.ChBodyEasyBox(6, 2, 4, 5000, True, True)
        crusher_base.SetPos(chrono.ChVectorD(-30, 1, 0))
        crusher_base.SetBodyFixed(True)
        crusher_base.GetVisualShape(0).SetColor(chrono.ChColor(0.3, 0.3, 0.3))
        self.system.Add(crusher_base)
        
        # Crushing jaws
        jaw_fixed = chrono.ChBodyEasyBox(2, 1.5, 3, 2000, True, True)
        jaw_fixed.SetPos(chrono.ChVectorD(-30, 3.75, 0))
        jaw_fixed.SetBodyFixed(True)
        jaw_fixed.GetVisualShape(0).SetColor(chrono.ChColor(0.5, 0.5, 0.5))
        self.system.Add(jaw_fixed)
        
        jaw_moving = chrono.ChBodyEasyBox(2, 1.5, 3, 2000, True, True)
        jaw_moving.SetPos(chrono.ChVectorD(-27, 3.75, 0))
        jaw_moving.GetVisualShape(0).SetColor(chrono.ChColor(0.5, 0.5, 0.5))
        self.system.Add(jaw_moving)
        
        # Crusher mechanism (crank-rocker)
        crusher_motor = chrono.ChLinkMotorRotationSpeed()
        crusher_motor.Initialize(jaw_moving, crusher_base, chrono.ChFrameD(chrono.ChVectorD(-27, 3.75, 0)))
        crusher_speed = chrono.ChFunction_Const(2.0)  # 2 RPM
        crusher_motor.SetSpeedFunction(crusher_speed)
        self.system.Add(crusher_motor)
        
    def create_raw_mill(self):
        mill_body = chrono.ChBodyEasyCylinder(chrono.ChAxis_Y, 3.0, 8.0, 8000, True, True)
        mill_body.SetPos(chrono.ChVectorD(-15, 4, 0))
        mill_body.GetVisualShape(0).SetColor(chrono.ChColor(0.4, 0.4, 0.6))
        self.system.Add(mill_body)
        
        mill_motor = chrono.ChLinkMotorRotationSpeed()
        mill_motor.Initialize(mill_body, ground, chrono.ChFrameD(chrono.ChVectorD(-15, 4, 0)))
        mill_speed = chrono.ChFunction_Const(15.0)  # 15 RPM
        mill_motor.SetSpeedFunction(mill_speed)
        self.system.Add(mill_motor)
        
        # Grinding media (simplified as internal bodies)
        for i in range(20):
            ball = chrono.ChBodyEasySphere(0.3, 200, True, True)
            angle = i * 2 * math.pi / 20
            ball.SetPos(chrono.ChVectorD(-15 + math.cos(angle)*2, 4 + math.sin(angle)*2, 0))
            ball.GetVisualShape(0).SetColor(chrono.ChColor(0.8, 0.2, 0.2))
            self.system.Add(ball)
            
    def create_cooler(self):
        cooler_body = chrono.ChBodyEasyBox(12, 3, 5, 3000, True, True)
        cooler_body.SetPos(chrono.ChVectorD(20, 1.5, 0))
        cooler_body.SetBodyFixed(True)
        cooler_body.GetVisualShape(0).SetColor(chrono.ChColor(0.2, 0.6, 0.8))
        self.system.Add(cooler_body)
        
        # Cooling plates
        for i in range(5):
            plate = chrono.ChBodyEasyBox(10, 0.1, 4, 100, True, True)
            plate.SetPos(chrono.ChVectorD(20, 2 + i*0.5, 0))
            plate.GetVisualShape(0).SetColor(chrono.ChColor(0.3, 0.3, 0.3))
            self.system.Add(plate)
            
    def create_cement_mill(self):
        mill_body = chrono.ChBodyEasyCylinder(chrono.ChAxis_Y, 2.5, 6.0, 6000, True, True)
        mill_body.SetPos(chrono.ChVectorD(35, 3, 0))
        mill_body.GetVisualShape(0).SetColor(chrono.ChColor(0.6, 0.4, 0.4))
        self.system.Add(mill_body)
        
        mill_motor = chrono.ChLinkMotorRotationSpeed()
        mill_motor.Initialize(mill_body, ground, chrono.ChFrameD(chrono.ChVectorD(35, 3, 0)))
        mill_speed = chrono.ChFunction_Const(18.0)  # 18 RPM
        mill_motor.SetSpeedFunction(mill_speed)
        self.system.Add(mill_motor)
        
    def create_silos(self):
        for i in range(3):
            silo = chrono.ChBodyEasyCylinder(chrono.ChAxis_Y, 4.0, 15.0, 4000, True, True)
            silo.SetPos(chrono.ChVectorD(50 + i*10, 7.5, 0))
            silo.SetBodyFixed(True)
            silo.GetVisualShape(0).SetColor(chrono.ChColor(0.7, 0.7, 0.9))
            self.system.Add(silo)
            
    def setup_sensors(self):
        # Temperature sensor in kiln
        self.temp_sensor = chrono.ChContactSensor()
        self.temp_sensor.SetName("Kiln Temperature")
        self.kiln_body.AddSensor(self.temp_sensor)
        
        # Pressure sensor (simulated)
        self.pressure_sensor = chrono.ChContactSensor()
        self.pressure_sensor.SetName("Cyclone Pressure")
        self.system.AddSensor(self.pressure_sensor)
        
    def connect_to_database(self):
        try:
            self.conn = psycopg2.connect(**self.db_params)
            self.cursor = self.conn.cursor()
            logger.info("Successfully connected to database")
            return True
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return False
            
    def initialize_database(self):
        try:
            # Create tables if they don't exist
            tables_sql = [
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    id SERIAL PRIMARY KEY,
                    plant_name VARCHAR(255) NOT NULL,
                    location VARCHAR(255) NOT NULL,
                    version INTEGER NOT NULL,
                    last_updated TIMESTAMP WITH TIME ZONE NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS sensor_metadata (
                    id SERIAL PRIMARY KEY,
                    sensor_type VARCHAR(255) NOT NULL,
                    location VARCHAR(255) NOT NULL,
                    calibration_status BOOLEAN NOT NULL,
                    sensor_id INTEGER NOT NULL UNIQUE
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS plant_data (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                    value DOUBLE PRECISION NOT NULL,
                    sensor_id INTEGER NOT NULL REFERENCES sensor_metadata(id) ON DELETE CASCADE,
                    plant_id INTEGER NOT NULL REFERENCES metadata(id) ON DELETE CASCADE
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS configuration (
                    id SERIAL PRIMARY KEY,
                    key VARCHAR(255) NOT NULL,
                    value VARCHAR(255) NOT NULL,
                    plant_id INTEGER NOT NULL REFERENCES metadata(id) ON DELETE CASCADE
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS system_config (
                    id SERIAL PRIMARY KEY,
                    setting VARCHAR(255) NOT NULL,
                    value BOOLEAN NOT NULL,
                    type VARCHAR(255) NOT NULL
                )
                """
            ]
            
            for sql in tables_sql:
                self.cursor.execute(sql)
                
            # Insert initial metadata
            self.cursor.execute("""
                INSERT INTO metadata (plant_name, location, version, last_updated) 
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, ("Cement Plant Digital Twin", "Virtual Location", 1, datetime.now(timezone.utc)))
            
            self.plant_id = self.cursor.fetchone()[0]
            
            # Insert sensor metadata
            sensors = [
                ("temperature", "rotary_kiln", True, 1),
                ("pressure", "cyclones", True, 2),
                ("fineness", "raw_mill", True, 3),
                ("gas_analysis", "kiln_exhaust", True, 4),
                ("mill_load", "cement_mill", True, 5)
            ]
            
            for sensor_type, location, calibrated, sensor_id in sensors:
                self.cursor.execute("""
                    INSERT INTO sensor_metadata (sensor_type, location, calibration_status, sensor_id)
                    VALUES (%s, %s, %s, %s)
                """, (sensor_type, location, calibrated, sensor_id))
                
            self.conn.commit()
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            self.conn.rollback()
            
    def simulate_temperature(self, base_temp, time):
        # Simulate temperature variations with some noise
        variation = 50 * math.sin(time * 0.1)  # Cyclic variation
        noise = np.random.normal(0, 10)  # Random noise
        return base_temp + variation + noise
        
    def simulate_pressure(self, base_pressure, time):
        variation = 0.1 * math.sin(time * 0.2)
        noise = np.random.normal(0, 0.02)
        return base_pressure + variation + noise
        
    def simulate_gas_emissions(self, time):
        co_base = 0.05
        nox_base = 0.3
        co_variation = 0.02 * math.sin(time * 0.15)
        nox_variation = 0.1 * math.sin(time * 0.12)
        return co_base + co_variation + np.random.normal(0, 0.005), nox_base + nox_variation + np.random.normal(0, 0.01)
        
    def simulate_mill_load(self, time):
        base_load = 75.0
        variation = 10 * math.sin(time * 0.08)
        return max(0, min(100, base_load + variation + np.random.normal(0, 2)))
        
    def simulate_fineness(self, time):
        base_fineness = 85.0
        variation = 3 * math.sin(time * 0.1)
        return base_fineness + variation + np.random.normal(0, 0.5)
        
    def check_critical_parameters(self, temp, co_emission):
        warnings = []
        if not self.critical_params['sintering_temp'][0] <= temp <= self.critical_params['sintering_temp'][1]:
            warnings.append(f"Temperature out of range: {temp:.1f}°C")
        if co_emission > self.critical_params['co_emission_limit']:
            warnings.append(f"CO emission too high: {co_emission:.3f}%")
        return warnings
        
    def store_sensor_data(self, sensor_id, value, timestamp):
        try:
            self.cursor.execute("""
                INSERT INTO plant_data (timestamp, value, sensor_id, plant_id)
                VALUES (%s, %s, %s, %s)
            """, (timestamp, value, sensor_id, self.plant_id))
        except Exception as e:
            logger.error(f"Failed to store sensor data: {e}")
            
    def run_simulation(self, duration=60.0, real_time=True):
        if not self.connect_to_database():
            logger.error("Cannot run simulation without database connection")
            return
            
        self.initialize_database()
        
        # Create visualization
        vis = irrlicht.ChVisualSystemIrrlicht()
        vis.AttachSystem(self.system)
        vis.SetWindowSize(1280, 720)
        vis.SetWindowTitle('Cement Plant Digital Twin')
        vis.Initialize()
        vis.AddCamera(chrono.ChVectorD(0, 10, -30), chrono.ChVectorD(0, 0, 0))
        vis.AddTypicalLights()
        
        logger.info("Starting cement plant digital twin simulation")
        
        start_time = time.time()
        sim_time = 0.0
        last_temp_update = 0.0
        last_gas_update = 0.0
        last_lab_update = 0.0
        
        while vis.Run() and sim_time < duration:
            vis.BeginScene()
            vis.Render()
            vis.EndScene()
            
            current_real_time = time.time() - start_time
            
            # Update simulation based on real-time or simulated time
            if real_time:
                step_size = 0.01
                self.system.DoStepDynamics(step_size)
                sim_time += step_size
            else:
                self.system.DoStepDynamics(0.01)
                sim_time += 0.01
                
            # Simulate sensor readings
            current_temp = self.simulate_temperature(1465, sim_time)
            current_pressure = self.simulate_pressure(-0.5, sim_time)
            current_co, current_nox = self.simulate_gas_emissions(sim_time)
            current_mill_load = self.simulate_mill_load(sim_time)
            current_fineness = self.simulate_fineness(sim_time)
            
            # Store data according to update frequencies
            current_timestamp = datetime.now(timezone.utc)
            
            # Temperature - every minute (simulated)
            if sim_time - last_temp_update >= 60.0:
                self.store_sensor_data(1, current_temp, current_timestamp)
                last_temp_update = sim_time
                
            # Gas analysis - every 10 seconds (simulated)
            if sim_time - last_gas_update >= 10.0:
                self.store_sensor_data(4, current_co, current_timestamp)
                last_gas_update = sim_time
                
            # Laboratory data (fineness) - every hour (simulated)
            if sim_time - last_lab_update >= 3600.0:
                self.store_sensor_data(3, current_fineness, current_timestamp)
                last_lab_update = sim_time
                
            # Continuous monitoring (pressure, mill load)
            self.store_sensor_data(2, current_pressure, current_timestamp)
            self.store_sensor_data(5, current_mill_load, current_timestamp)
            
            # Check critical parameters
            warnings = self.check_critical_parameters(current_temp, current_co)
            for warning in warnings:
                logger.warning(f"CRITICAL: {warning}")
                
            # Commit database transactions periodically
            if sim_time % 30.0 < 0.01:  # Every 30 simulated seconds
                try:
                    self.conn.commit()
                    # Update last_updated timestamp
                    self.cursor.execute("""
                        UPDATE metadata SET last_updated = %s WHERE id = %s
                    """, (current_timestamp, self.plant_id))
                except Exception as e:
                    logger.error(f"Database commit failed: {e}")
                    
            # Display real-time data
            if int(sim_time) % 5 == 0 and int(sim_time) != int(sim_time - 0.01):
                logger.info(f"Time: {sim_time:.1f}s | Temp: {current_temp:.1f}°C | CO: {current_co:.3f}% | Load: {current_mill_load:.1f}%")
                
        # Final database commit and cleanup
        try:
            self.conn.commit()
            self.cursor.close()
            self.conn.close()
        except Exception as e:
            logger.error(f"Final cleanup failed: {e}")
            
        logger.info("Simulation completed")
        
if __name__ == "__main__":
    try:
        twin = CementPlantDigitalTwin()
        twin.run_simulation(duration=300.0, real_time=True)  # 5-minute simulation
    except KeyboardInterrupt:
        logger.info("Simulation interrupted by user")
    except Exception as e:
        logger.error(f"Simulation error: {e}")
        sys.exit(1)