import pychrono as chrono
import pychrono.irrlicht as chronoirr
import math
import random
import time
from datetime import datetime, timedelta
import sqlite3
import json

class SteelPlantDigitalTwin:
    def __init__(self):
        # Initialize PyChrono system
        self.system = chrono.ChSystemNSC()
        self.system.SetSolverType(chrono.ChSolver.Type_BARZILAIBORWEIN)
        
        # Simulation parameters
        self.sim_time = 0
        self.real_time_factor = 1.0
        self.update_frequency = 3.0  # seconds
        
        # Database setup
        self.setup_database()
        
        # Initialize equipment and sensors
        self.setup_equipment()
        self.setup_sensors()
        
        # Current production batch
        self.current_batch = None
        self.batch_start_time = None
        
        # Visualization
        self.vis = None
        
    def setup_database(self):
        """Initialize SQLite database with schema"""
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        # Create tables based on schema
        tables_sql = [
            """CREATE TABLE equipment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                type VARCHAR(50) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                installation_date DATE NOT NULL,
                last_maintenance TIMESTAMP,
                next_maintenance TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""",
            
            """CREATE TABLE sensors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER NOT NULL,
                sensor_type VARCHAR(50) NOT NULL,
                sensor_name VARCHAR(100) NOT NULL,
                location VARCHAR(100),
                unit VARCHAR(20),
                calibration_date DATE,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (equipment_id) REFERENCES equipment(id)
            )""",
            
            """CREATE TABLE sensor_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_id INTEGER NOT NULL,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                value DECIMAL(10,4) NOT NULL,
                quality INTEGER DEFAULT 100,
                batch_id VARCHAR(50),
                FOREIGN KEY (sensor_id) REFERENCES sensors(id)
            )""",
            
            """CREATE TABLE production_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_number VARCHAR(50) NOT NULL UNIQUE,
                steel_grade VARCHAR(50) NOT NULL,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP,
                status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
                target_speed DECIMAL(8,2),
                actual_speed DECIMAL(8,2),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""",
            
            """CREATE TABLE quality_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                metric_name VARCHAR(50) NOT NULL,
                metric_value DECIMAL(10,4) NOT NULL,
                target_value DECIMAL(10,4),
                tolerance_min DECIMAL(10,4),
                tolerance_max DECIMAL(10,4),
                defect_type VARCHAR(50),
                defect_severity INTEGER,
                measured_at TIMESTAMP NOT NULL,
                FOREIGN KEY (batch_id) REFERENCES production_batches(id)
            )""",
            
            """CREATE TABLE equipment_wear (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER NOT NULL,
                wear_parameter VARCHAR(50) NOT NULL,
                current_value DECIMAL(10,4) NOT NULL,
                initial_value DECIMAL(10,4) NOT NULL,
                wear_rate DECIMAL(8,4),
                measurement_date DATE NOT NULL,
                operating_hours INTEGER NOT NULL,
                FOREIGN KEY (equipment_id) REFERENCES equipment(id)
            )""",
            
            """CREATE TABLE alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_id INTEGER,
                batch_id INTEGER,
                alert_type VARCHAR(50) NOT NULL,
                severity VARCHAR(20) NOT NULL,
                description TEXT NOT NULL,
                threshold_value DECIMAL(10,4),
                actual_value DECIMAL(10,4),
                trigger_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                acknowledged BOOLEAN DEFAULT FALSE,
                acknowledged_by VARCHAR(100),
                acknowledged_at TIMESTAMP,
                resolved BOOLEAN DEFAULT FALSE,
                resolved_at TIMESTAMP,
                FOREIGN KEY (sensor_id) REFERENCES sensors(id),
                FOREIGN KEY (batch_id) REFERENCES production_batches(id)
            )""",
            
            """CREATE TABLE process_parameters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                parameter_name VARCHAR(50) NOT NULL,
                parameter_value DECIMAL(10,4) NOT NULL,
                setpoint DECIMAL(10,4),
                unit VARCHAR(20),
                recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (batch_id) REFERENCES production_batches(id)
            )"""
        ]
        
        for sql in tables_sql:
            self.cursor.execute(sql)
        
        # Insert initial equipment data
        self.initialize_equipment_data()
        self.initialize_sensor_data()
        
    def initialize_equipment_data(self):
        """Insert initial equipment records"""
        equipment_data = [
            ('Промежуточный ковш', 'ковш', '2023-01-15'),
            ('Кристаллизатор 1', 'кристаллизатор', '2023-01-20'),
            ('Зона вторичного охлаждения', 'охлаждение', '2023-01-25'),
            ('Тянущие валки 1-4', 'валки', '2023-02-01'),
            ('Устройство разрезки', 'разрезка', '2023-02-05')
        ]
        
        for name, eq_type, install_date in equipment_data:
            self.cursor.execute(
                "INSERT INTO equipment (name, type, installation_date) VALUES (?, ?, ?)",
                (name, eq_type, install_date)
            )
        
        self.conn.commit()
    
    def initialize_sensor_data(self):
        """Insert initial sensor records"""
        sensor_data = [
            (2, 'термопара', 'Температура стали в кристаллизаторе', 'верхняя зона', '°C'),
            (2, 'термопара', 'Температура воды охлаждения', 'выход', '°C'),
            (3, 'расходомер', 'Расход воды охлаждения', 'зона 1', 'л/мин'),
            (3, 'расходомер', 'Расход воды охлаждения', 'зона 2', 'л/мин'),
            (4, 'датчик скорости', 'Скорость валков', 'валк 1', 'м/мин'),
            (4, 'акселерометр', 'Вибрация валков', 'опора 1', 'g'),
            (5, 'датчик положения', 'Положение резака', 'ось X', 'мм')
        ]
        
        for eq_id, s_type, s_name, location, unit in sensor_data:
            self.cursor.execute(
                """INSERT INTO sensors (equipment_id, sensor_type, sensor_name, location, unit) 
                VALUES (?, ?, ?, ?, ?)""",
                (eq_id, s_type, s_name, location, unit)
            )
        
        self.conn.commit()
    
    def setup_equipment(self):
        """Create physical bodies for the continuous casting machine"""
        # Create ground
        ground = chrono.ChBodyEasyBox(20, 1, 10, 1000, True, False)
        ground.SetPos(chrono.ChVectorD(0, -0.5, 0))
        ground.SetBodyFixed(True)
        self.system.Add(ground)
        
        # Intermediate ladle (tundish)
        self.tundish = chrono.ChBodyEasyCylinder(0.8, 1.2, 5000, True, False)
        self.tundish.SetPos(chrono.ChVectorD(0, 3, 0))
        self.tundish.SetRot(chrono.Q_from_AngX(chrono.CH_C_PI_2))
        self.system.Add(self.tundish)
        
        # Mold (crystallizer)
        self.mold = chrono.ChBodyEasyBox(0.5, 2, 0.3, 8000, True, False)
        self.mold.SetPos(chrono.ChVectorD(0, 1.5, 0))
        self.system.Add(self.mold)
        
        # Steel strand (continuously cast steel)
        self.steel_strand = chrono.ChBodyEasyBox(0.3, 8, 0.2, 7800, True, False)
        self.steel_strand.SetPos(chrono.ChVectorD(0, -2, 0))
        self.system.Add(self.steel_strand)
        
        # Withdrawal rolls
        self.rolls = []
        roll_positions = [(0, -4, 0), (0, -6, 0)]
        for i, pos in enumerate(roll_positions):
            roll = chrono.ChBodyEasyCylinder(0.2, 0.8, 2000, True, False)
            roll.SetPos(chrono.ChVectorD(pos[0], pos[1], pos[2]))
            roll.SetRot(chrono.Q_from_AngX(chrono.CH_C_PI_2))
            self.system.Add(roll)
            self.rolls.append(roll)
            
            # Add rotational motor for rolls
            motor = chrono.ChLinkMotorRotationSpeed()
            motor.Initialize(roll, ground, chrono.ChFrameD(chrono.ChVectorD(pos[0], pos[1], pos[2])))
            motor.SetSpeedFunction(chrono.ChFunction_Const(0.5))  # 0.5 rad/s
            self.system.Add(motor)
        
        # Cutting device
        self.cutter = chrono.ChBodyEasyBox(0.1, 0.3, 0.5, 500, True, False)
        self.cutter.SetPos(chrono.ChVectorD(0, -8, 0))
        self.system.Add(self.cutter)
        
        # Add cooling spray (visual effect)
        self.cooling_spray = chrono.ChBodyEasySphere(0.1, 100, True, False)
        self.cooling_spray.SetPos(chrono.ChVectorD(0, -3, 0))
        self.system.Add(self.cooling_spray)
    
    def setup_sensors(self):
        """Initialize sensor simulation parameters"""
        self.sensor_values = {
            'mold_temperature': 1500.0,  # Initial steel temperature
            'cooling_water_temp': 25.0,
            'water_flow_zone1': 120.0,
            'water_flow_zone2': 100.0,
            'roll_speed': 1.2,
            'roll_vibration': 0.05,
            'cutter_position': 0.0
        }
        
        self.sensor_noise = {
            'mold_temperature': 2.0,
            'cooling_water_temp': 0.5,
            'water_flow_zone1': 2.0,
            'water_flow_zone2': 2.0,
            'roll_speed': 0.1,
            'roll_vibration': 0.01,
            'cutter_position': 1.0
        }
    
    def start_new_batch(self, steel_grade='Ст3сп', target_speed=1.2):
        """Start a new production batch"""
        batch_number = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.batch_start_time = datetime.now()
        
        self.cursor.execute(
            """INSERT INTO production_batches 
            (batch_number, steel_grade, start_time, target_speed, actual_speed, status) 
            VALUES (?, ?, ?, ?, ?, ?)""",
            (batch_number, steel_grade, self.batch_start_time, target_speed, target_speed, 'in_progress')
        )
        
        self.current_batch = self.cursor.lastrowid
        self.conn.commit()
        
        print(f"Started new batch: {batch_number}, Grade: {steel_grade}")
        
        # Initialize quality metrics for this batch
        self.initialize_quality_metrics()
    
    def initialize_quality_metrics(self):
        """Initialize quality monitoring for current batch"""
        metrics = [
            ('температура_кристаллизации', 1500, 1480, 1520),
            ('скорость_разливки', 1.2, 1.0, 1.4),
            ('равномерность_охлаждения', 95.0, 90.0, 100.0),
            ('вибрация_оборудования', 0.05, 0.0, 0.1)
        ]
        
        for metric, target, min_tol, max_tol in metrics:
            self.cursor.execute(
                """INSERT INTO quality_metrics 
                (batch_id, metric_name, metric_value, target_value, tolerance_min, tolerance_max, measured_at) 
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self.current_batch, metric, target, target, min_tol, max_tol, datetime.now())
            )
        
        self.conn.commit()
    
    def simulate_sensor_readings(self):
        """Generate simulated sensor readings with realistic behavior"""
        # Mold temperature simulation (decreases slightly due to cooling)
        base_temp = 1500.0
        cooling_effect = self.sensor_values['water_flow_zone1'] * 0.1
        temp_variation = math.sin(self.sim_time * 0.5) * 10
        self.sensor_values['mold_temperature'] = base_temp - cooling_effect + temp_variation
        
        # Cooling water temperature (increases due to heat exchange)
        self.sensor_values['cooling_water_temp'] = 25.0 + (self.sensor_values['mold_temperature'] - 1400) * 0.02
        
        # Roll speed with slight variations
        target_speed = 1.2
        speed_variation = math.sin(self.sim_time * 0.3) * 0.05
        self.sensor_values['roll_speed'] = target_speed + speed_variation
        
        # Vibration increases with operating time
        base_vibration = 0.05 + (self.sim_time / 3600) * 0.001  # Wear over time
        vibration_variation = math.sin(self.sim_time * 2) * 0.02
        self.sensor_values['roll_vibration'] = base_vibration + vibration_variation
        
        # Cutter position (moves back and forth)
        self.sensor_values['cutter_position'] = math.sin(self.sim_time * 0.2) * 50
        
        # Add noise to readings
        for key in self.sensor_values:
            if key in self.sensor_noise:
                noise = random.gauss(0, self.sensor_noise[key] * 0.1)
                self.sensor_values[key] += noise
    
    def log_sensor_data(self):
        """Log current sensor readings to database"""
        if not self.current_batch:
            return
            
        sensor_mapping = {
            1: 'mold_temperature',
            2: 'cooling_water_temp', 
            3: 'water_flow_zone1',
            4: 'water_flow_zone2',
            5: 'roll_speed',
            6: 'roll_vibration',
            7: 'cutter_position'
        }
        
        current_time = datetime.now()
        batch_id_str = f"BATCH_{self.current_batch}"
        
        for sensor_id, value_key in sensor_mapping.items():
            value = self.sensor_values[value_key]
            quality = 100 - abs(random.gauss(0, 5))  # Simulate measurement quality
            
            self.cursor.execute(
                """INSERT INTO sensor_data 
                (sensor_id, timestamp, value, quality, batch_id) 
                VALUES (?, ?, ?, ?, ?)""",
                (sensor_id, current_time, float(value), int(quality), batch_id_str)
            )
        
        # Update process parameters
        process_params = [
            ('скорость_разливки', self.sensor_values['roll_speed'], 'м/мин'),
            ('температура_стали', self.sensor_values['mold_temperature'], '°C'),
            ('расход_воды', self.sensor_values['water_flow_zone1'], 'л/мин')
        ]
        
        for param_name, param_value, unit in process_params:
            self.cursor.execute(
                """INSERT INTO process_parameters 
                (batch_id, parameter_name, parameter_value, setpoint, unit) 
                VALUES (?, ?, ?, ?, ?)""",
                (self.current_batch, param_name, float(param_value), float(param_value), unit)
            )
        
        self.conn.commit()
    
    def check_alerts(self):
        """Check for abnormal conditions and generate alerts"""
        if not self.current_batch:
            return
            
        alerts = []
        
        # Temperature alert
        if self.sensor_values['mold_temperature'] < 1450:
            alerts.append((
                None, self.current_batch, 'низкая_температура', 'high',
                f'Температура стали ниже допустимой: {self.sensor_values["mold_temperature"]:.1f}°C',
                1450, self.sensor_values['mold_temperature']
            ))
        
        # Vibration alert
        if self.sensor_values['roll_vibration'] > 0.08:
            alerts.append((
                6, self.current_batch, 'высокая_вибрация', 'medium',
                f'Высокая вибрация валков: {self.sensor_values["roll_vibration"]:.3f}g',
                0.08, self.sensor_values['roll_vibration']
            ))
        
        # Speed deviation alert
        target_speed = 1.2
        speed_deviation = abs(self.sensor_values['roll_speed'] - target_speed)
        if speed_deviation > 0.15:
            alerts.append((
                5, self.current_batch, 'отклонение_скорости', 'medium',
                f'Отклонение скорости разливки: {speed_deviation:.2f} м/мин',
                0.15, speed_deviation
            ))
        
        # Insert alerts into database
        for alert_data in alerts:
            self.cursor.execute(
                """INSERT INTO alerts 
                (sensor_id, batch_id, alert_type, severity, description, threshold_value, actual_value) 
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                alert_data
            )
        
        if alerts:
            self.conn.commit()
            print(f"Generated {len(alerts)} alert(s)")
    
    def update_quality_metrics(self):
        """Update quality metrics based on current process conditions"""
        if not self.current_batch:
            return
            
        current_time = datetime.now()
        
        # Calculate defect probability based on process deviations
        temp_deviation = abs(self.sensor_values['mold_temperature'] - 1500) / 50
        speed_deviation = abs(self.sensor_values['roll_speed'] - 1.2) / 0.2
        vibration_level = self.sensor_values['roll_vibration'] / 0.1
        
        defect_probability = (temp_deviation + speed_deviation + vibration_level) / 3 * 10
        defect_severity = min(10, max(0, int(defect_probability)))
        
        defect_type = None
        if defect_severity > 5:
            if temp_deviation > speed_deviation:
                defect_type = 'раковины'
            else:
                defect_type = 'трещины'
        
        self.cursor.execute(
            """UPDATE quality_metrics 
            SET metric_value = ?, defect_type = ?, defect_severity = ?, measured_at = ?
            WHERE batch_id = ? AND metric_name = ?""",
            (100 - defect_severity * 10, defect_type, defect_severity, current_time,
             self.current_batch, 'равномерность_охлаждения')
        )
        
        self.conn.commit()
    
    def update_equipment_wear(self):
        """Simulate equipment wear over time"""
        current_date = datetime.now().date()
        
        # Calculate operating hours (simplified)
        operating_hours = int(self.sim_time / 3600)
        
        wear_data = [
            (2, 'износ_футеровки', 0.1, 100.0, 0.001),
            (4, 'износ_подшипников', 0.05, 50.0, 0.002),
            (5, 'износ_резцов', 0.02, 20.0, 0.005)
        ]
        
        for eq_id, wear_param, initial, current, rate in wear_data:
            # Increase wear based on operating time
            new_wear = current + (operating_hours * rate)
            
            self.cursor.execute(
                """INSERT INTO equipment_wear 
                (equipment_id, wear_parameter, current_value, initial_value, wear_rate, measurement_date, operating_hours) 
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (eq_id, wear_param, new_wear, initial, rate, current_date, operating_hours)
            )
        
        self.conn.commit()
    
    def setup_visualization(self):
        """Set up Irrlicht visualization"""
        self.vis = chronoirr.ChIrrApp(self.system, "Digital Twin: Continuous Steel Casting", chronoirr.dimension2du(1280, 720))
        self.vis.AddTypicalSky()
        self.vis.AddTypicalLights()
        self.vis.AddTypicalCamera(chronoirr.vector3df(5, 3, 5))
        
        # Add material properties for better visualization
        steel_material = chrono.ChVisualMaterial()
        steel_material.SetDiffuseColor(chrono.ChColor(0.7, 0.7, 0.8))
        steel_material.SetSpecularColor(chrono.ChColor(0.9, 0.9, 0.9))
        
        self.steel_strand.GetVisualShape(0).SetMaterial(0, steel_material)
    
    def run_simulation(self, duration_hours=1, with_visualization=True):
        """Run the main simulation loop"""
        if with_visualization:
            self.setup_visualization()
            self.vis.Run()
        
        print("Starting continuous casting simulation...")
        self.start_new_batch()
        
        last_update = time.time()
        frame_count = 0
        
        while self.sim_time < duration_hours * 3600:
            current_time = time.time()
            elapsed_real = current_time - last_update
            
            if elapsed_real >= self.update_frequency:
                # Update simulation
                self.simulate_sensor_readings()
                self.log_sensor_data()
                self.check_alerts()
                self.update_quality_metrics()
                
                if frame_count % 10 == 0:  # Update wear less frequently
                    self.update_equipment_wear()
                
                # Print status
                if frame_count % 5 == 0:
                    print(f"Time: {self.sim_time/3600:.2f}h | "
                          f"Temp: {self.sensor_values['mold_temperature']:.1f}°C | "
                          f"Speed: {self.sensor_values['roll_speed']:.2f} m/min")
                
                last_update = current_time
                frame_count += 1
            
            # Step the simulation
            step_size = 0.01
            self.system.DoStepDynamics(step_size)
            self.sim_time += step_size * self.real_time_factor
            
            if with_visualization:
                self.vis.BeginScene()
                self.vis.DrawAll()
                self.vis.EndScene()
        
        # Complete the batch
        if self.current_batch:
            self.cursor.execute(
                "UPDATE production_batches SET end_time = ?, status = 'completed' WHERE id = ?",
                (datetime.now(), self.current_batch)
            )
            self.conn.commit()
        
        print("Simulation completed")
        
        # Print summary
        self.print_simulation_summary()
    
    def print_simulation_summary(self):
        """Print summary of simulation results"""
        print("\n=== SIMULATION SUMMARY ===")
        
        # Batch information
        self.cursor.execute(
            "SELECT batch_number, steel_grade, start_time, end_time FROM production_batches WHERE id = ?",
            (self.current_batch,)
        )
        batch_info = self.cursor.fetchone()
        print(f"Batch: {batch_info[0]}")
        print(f"Steel Grade: {batch_info[1]}")
        print(f"Duration: {batch_info[3] - batch_info[2]}")
        
        # Quality metrics
        self.cursor.execute(
            "SELECT metric_name, metric_value, defect_type, defect_severity FROM quality_metrics WHERE batch_id = ?",
            (self.current_batch,)
        )
        quality_metrics = self.cursor.fetchall()
        print("\nQuality Metrics:")
        for metric in quality_metrics:
            print(f"  {metric[0]}: {metric[1]:.2f} | Defect: {metric[2] or 'None'} | Severity: {metric[3]}")
        
        # Alerts
        self.cursor.execute(
            "SELECT COUNT(*) FROM alerts WHERE batch_id = ? AND severity = 'high'",
            (self.current_batch,)
        )
        high_alerts = self.cursor.fetchone()[0]
        print(f"\nHigh Severity Alerts: {high_alerts}")
        
        # Equipment wear
        self.cursor.execute(
            "SELECT equipment.name, equipment_wear.wear_parameter, equipment_wear.current_value "
            "FROM equipment_wear JOIN equipment ON equipment_wear.equipment_id = equipment.id "
            "ORDER BY equipment_wear.current_value DESC LIMIT 3"
        )
        wear_info = self.cursor.fetchall()
        print("\nTop 3 Equipment Wear:")
        for wear in wear_info:
            print(f"  {wear[0]} - {wear[1]}: {wear[2]:.3f}")

# Main execution
if __name__ == "__main__":
    digital_twin = SteelPlantDigitalTwin()
    
    # Run simulation for 1 hour (simulated time) with visualization
    try:
        digital_twin.run_simulation(duration_hours=1, with_visualization=True)
    except KeyboardInterrupt:
        print("\nSimulation interrupted by user")
    
    # Close database connection
    digital_twin.conn.close()