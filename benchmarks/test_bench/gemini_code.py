import pychrono as chrono
import pychrono.irrlicht as chronoirr
import pychrono.postprocess as chronopost
import random
import datetime
import psycopg2

# Database connection details (replace with your actual credentials)
DB_HOST = "localhost"
DB_NAME = "cement_plant_db"
DB_USER = "your_username"
DB_PASSWORD = "your_password"

# Global dictionary to store sensor metadata and their mapping to chrono objects
sensor_metadata_map = {}
chrono_body_to_sensor_id = {}
plant_id = None # Will be set after inserting plant metadata

def create_database_schema():
    """Creates the necessary tables in the PostgreSQL database."""
    conn = None
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                id serial PRIMARY KEY,
                plant_name VARCHAR(255) NOT NULL,
                location VARCHAR(255) NOT NULL,
                version integer NOT NULL,
                last_updated TIMESTAMP WITH TIME ZONE NOT NULL
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS sensor_metadata (
                id serial PRIMARY KEY,
                sensor_type VARCHAR(255) NOT NULL,
                location VARCHAR(255) NOT NULL,
                calibration_status BOOLEAN NOT NULL,
                sensor_id integer NOT NULL UNIQUE
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS plant_data (
                id serial PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                value DOUBLE PRECISION NOT NULL,
                sensor_id integer NOT NULL REFERENCES sensor_metadata(id) ON DELETE CASCADE,
                plant_id integer NOT NULL REFERENCES metadata(id) ON DELETE CASCADE
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS configuration (
                id serial PRIMARY KEY,
                key VARCHAR(255) NOT NULL,
                value VARCHAR(255) NOT NULL,
                plant_id integer NOT NULL REFERENCES metadata(id) ON DELETE CASCADE
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                id serial PRIMARY KEY,
                setting VARCHAR(255) NOT NULL,
                value BOOLEAN NOT NULL,
                type VARCHAR(255) NOT NULL
            );
        """)

        conn.commit()
        print("Database schema created or already exists.")

    except psycopg2.Error as e:
        print(f"Error creating database schema: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()

def insert_plant_metadata(plant_name, location, version):
    """Inserts plant metadata into the database and returns its ID."""
    conn = None
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO metadata (plant_name, location, version, last_updated) VALUES (%s, %s, %s, %s) RETURNING id;",
            (plant_name, location, version, datetime.datetime.now(datetime.timezone.utc))
        )
        metadata_id = cur.fetchone()[0]
        conn.commit()
        print(f"Plant metadata inserted with ID: {metadata_id}")
        return metadata_id
    except psycopg2.Error as e:
        print(f"Error inserting plant metadata: {e}")
        return None
    finally:
        if conn:
            cur.close()
            conn.close()

def insert_sensor_metadata(sensor_type, location, calibration_status, sensor_chrono_id):
    """Inserts sensor metadata into the database and stores its ID."""
    conn = None
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sensor_metadata (sensor_type, location, calibration_status, sensor_id) VALUES (%s, %s, %s, %s) RETURNING id;",
            (sensor_type, location, calibration_status, sensor_chrono_id)
        )
        db_sensor_id = cur.fetchone()[0]
        conn.commit()
        sensor_metadata_map[sensor_chrono_id] = db_sensor_id
        return db_sensor_id
    except psycopg2.Error as e:
        print(f"Error inserting sensor metadata: {e}")
        return None
    finally:
        if conn:
            cur.close()
            conn.close()

def log_plant_data(timestamp, value, sensor_chrono_id):
    """Logs sensor data to the database."""
    global plant_id
    if plant_id is None:
        print("Error: Plant ID not set. Cannot log data.")
        return

    db_sensor_id = sensor_metadata_map.get(sensor_chrono_id)
    if db_sensor_id is None:
        print(f"Error: Sensor chrono ID {sensor_chrono_id} not found in sensor_metadata_map. Cannot log data.")
        return

    conn = None
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO plant_data (timestamp, value, sensor_id, plant_id) VALUES (%s, %s, %s, %s);",
            (timestamp, value, db_sensor_id, plant_id)
        )
        conn.commit()
    except psycopg2.Error as e:
        print(f"Error logging plant data: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()

class CementPlantSimulation:
    def __init__(self):
        # 1. Initialize the Chrono system
        self.system = chrono.ChSystemSMC()
        self.system.SetGravity(chrono.ChVectorD(0, -9.81, 0)) # Standard gravity

        # Materials
        self.steel_mat = chrono.ChMaterialSurfaceSMC()
        self.steel_mat.SetFriction(0.6)
        self.steel_mat.SetRestitution(0.1)

        self.refractory_mat = chrono.ChMaterialSurfaceSMC()
        self.refractory_mat.SetFriction(0.4)
        self.refractory_mat.SetRestitution(0.05)

        self.clinker_mat = chrono.ChMaterialSurfaceSMC() # For simulated clinker particles
        self.clinker_mat.SetFriction(0.8)
        self.clinker_mat.SetRestitution(0.2)

        self.sensor_count = 0 # To assign unique sensor IDs for logging

        self._create_equipment()
        self._setup_joints_and_constraints()
        self._setup_sensors()

    def _create_equipment(self):
        # 3. Create physical bodies representing equipment

        # Crusher (дробилка) - Represented as a static box for simplicity
        self.crusher = chrono.ChBodyEasyBox(10, 5, 5, 1000)
        self.crusher.SetPos(chrono.ChVectorD(-50, 0, 0))
        self.crusher.SetBodyFixed(True)
        self.crusher.SetMaterialSurface(self.steel_mat)
        self.system.Add(self.crusher)
        self.crusher.AddAsset(chrono.ChColorAsset(chrono.ChColor(0.2, 0.2, 0.8))) # Blue

        # Raw Mill (сырьевая мельница) - Rotating cylinder
        self.raw_mill_drum = chrono.ChBodyEasyCylinder(5, 15, 50000)
        self.raw_mill_drum.SetPos(chrono.ChVectorD(-20, 0, 0))
        self.raw_mill_drum.SetRot(chrono.Q_from_Euler123(chrono.ChVectorD(0, 0, chrono.CH_C_PI_2))) # Rotate to be horizontal
        self.raw_mill_drum.SetMaterialSurface(self.steel_mat)
        self.system.Add(self.raw_mill_drum)
        self.raw_mill_drum.AddAsset(chrono.ChColorAsset(chrono.ChColor(0.8, 0.5, 0.2))) # Orange

        # Rotary Kiln (вращающаяся печь) - Large rotating cylinder
        self.rotary_kiln = chrono.ChBodyEasyCylinder(8, 60, 200000)
        self.rotary_kiln.SetPos(chrono.ChVectorD(30, 5, 0))
        self.rotary_kiln.SetRot(chrono.Q_from_Euler123(chrono.ChVectorD(0, 0, chrono.CH_C_PI_2 + 0.05))) # Slight incline
        self.rotary_kiln.SetMaterialSurface(self.refractory_mat)
        self.system.Add(self.rotary_kiln)
        self.rotary_kiln.AddAsset(chrono.ChColorAsset(chrono.ChColor(0.9, 0.1, 0.1))) # Red

        # Clinker Cooler (колосниковый холодильник) - Static box with "cooling" effect
        self.clinker_cooler = chrono.ChBodyEasyBox(15, 5, 10, 1500)
        self.clinker_cooler.SetPos(chrono.ChVectorD(70, -2, 0))
        self.clinker_cooler.SetBodyFixed(True)
        self.clinker_cooler.SetMaterialSurface(self.steel_mat)
        self.system.Add(self.clinker_cooler)
        self.clinker_cooler.AddAsset(chrono.ChColorAsset(chrono.ChColor(0.1, 0.5, 0.8))) # Light blue

        # Cement Mill (цементная мельница) - Another rotating cylinder
        self.cement_mill_drum = chrono.ChBodyEasyCylinder(5, 15, 50000)
        self.cement_mill_drum.SetPos(chrono.ChVectorD(100, 0, 0))
        self.cement_mill_drum.SetRot(chrono.Q_from_Euler123(chrono.ChVectorD(0, 0, chrono.CH_C_PI_2)))
        self.cement_mill_drum.SetMaterialSurface(self.steel_mat)
        self.system.Add(self.cement_mill_drum)
        self.cement_mill_drum.AddAsset(chrono.ChColorAsset(chrono.ChColor(0.8, 0.5, 0.2))) # Orange

        # Silos (силосы) - Static cylinders
        self.silo1 = chrono.ChBodyEasyCylinder(5, 20, 2000)
        self.silo1.SetPos(chrono.ChVectorD(130, 8, -10))
        self.silo1.SetBodyFixed(True)
        self.silo1.SetMaterialSurface(self.steel_mat)
        self.system.Add(self.silo1)
        self.silo1.AddAsset(chrono.ChColorAsset(chrono.ChColor(0.5, 0.5, 0.5))) # Grey

        self.silo2 = chrono.ChBodyEasyCylinder(5, 20, 2000)
        self.silo2.SetPos(chrono.ChVectorD(130, 8, 10))
        self.silo2.SetBodyFixed(True)
        self.silo2.SetMaterialSurface(self.steel_mat)
        self.system.Add(self.silo2)
        self.silo2.AddAsset(chrono.ChColorAsset(chrono.ChColor(0.5, 0.5, 0.5))) # Grey

    def _setup_joints_and_constraints(self):
        # 5. Define joints and constraints between bodies

        # Raw Mill Rotation
        self.raw_mill_motor = chrono.ChLinkMotorRotationSpeed()
        self.raw_mill_motor.Initialize(self.raw_mill_drum, self.system.GetGround(),
                                       chrono.ChFrameD(self.raw_mill_drum.GetPos(),
                                                       chrono.Q_from_Euler123(chrono.ChVectorD(0, 0, chrono.CH_C_PI_2))))
        self.raw_mill_motor.SetSpeedFunction(chrono.ChFunction_Const(0.5 * chrono.CH_C_2PI / 60))  # 0.5 RPM
        self.system.Add(self.raw_mill_motor)

        # Rotary Kiln Rotation
        self.kiln_motor = chrono.ChLinkMotorRotationSpeed()
        self.kiln_motor.Initialize(self.rotary_kiln, self.system.GetGround(),
                                   chrono.ChFrameD(self.rotary_kiln.GetPos(),
                                                   chrono.Q_from_Euler123(chrono.ChVectorD(0, 0, chrono.CH_C_PI_2))))
        self.kiln_motor.SetSpeedFunction(chrono.ChFunction_Const(0.1 * chrono.CH_C_2PI / 60))  # 0.1 RPM
        self.system.Add(self.kiln_motor)

        # Cement Mill Rotation
        self.cement_mill_motor = chrono.ChLinkMotorRotationSpeed()
        self.cement_mill_motor.Initialize(self.cement_mill_drum, self.system.GetGround(),
                                          chrono.ChFrameD(self.cement_mill_drum.GetPos(),
                                                          chrono.Q_from_Euler123(chrono.ChVectorD(0, 0, chrono.CH_C_PI_2))))
        self.cement_mill_motor.SetSpeedFunction(chrono.ChFunction_Const(0.5 * chrono.CH_C_2PI / 60))  # 0.5 RPM
        self.system.Add(self.cement_mill_motor)

    def _setup_sensors(self):
        # 6. Implement sensors to measure simulation parameters

        # Temperature in Kiln (температура в печи)
        self.kiln_temp_sensor_id = self._add_sensor("температура", "вращающаяся печь", True)
        chrono_body_to_sensor_id[self.kiln_temp_sensor_id] = self.rotary_kiln

        # Draft in Cyclones (разрежение в циклонах) - Conceptual, not directly simulated in Chrono
        # Will be a simulated value based on kiln operation
        self.cyclone_draft_sensor_id = self._add_sensor("разрежение", "циклоны", True)
        # No direct Chrono body mapping for conceptual sensors

        # Fineness of Grinding (тонкость помола) - Conceptual, tied to mill operation
        self.grinding_fineness_sensor_id = self._add_sensor("тонкость помола", "цементная мельница", True)
        chrono_body_to_sensor_id[self.grinding_fineness_sensor_id] = self.cement_mill_drum

        # Exhaust Gas Composition (состав отходящих газов (CO, NOx)) - Conceptual
        self.co_gas_sensor_id = self._add_sensor("CO", "возле дымовой трубы", True)
        self.nox_gas_sensor_id = self._add_sensor("NOx", "возле дымовой трубы", True)

        # Mill Loading Level (уровень загрузки мельницы) - Conceptual, tied to material flow
        self.mill_loading_sensor_id = self._add_sensor("уровень загрузки", "сырьевая мельница", True)
        chrono_body_to_sensor_id[self.mill_loading_sensor_id] = self.raw_mill_drum


    def _add_sensor(self, sensor_type, location, calibration_status):
        self.sensor_count += 1
        insert_sensor_metadata(sensor_type, location, calibration_status, self.sensor_count)
        return self.sensor_count

    def get_sensor_data(self, current_time):
        data = {}

        # Temperature in Kiln (simulated, based on time)
        # Critical range: 1450-1480°C
        kiln_temp = 1460 + 10 * chrono.ChFunction_Sine().Get_y(current_time / 1000) + random.uniform(-2, 2)
        data[self.kiln_temp_sensor_id] = kiln_temp

        # Draft in Cyclones (simulated, conceptual)
        # Let's say steady state is around -100 Pa, with some fluctuations
        cyclone_draft = -100 + 10 * chrono.ChFunction_Sine().Get_y(current_time / 500) + random.uniform(-5, 5)
        data[self.cyclone_draft_sensor_id] = cyclone_draft

        # Fineness of Grinding (simulated, conceptual)
        # Example: a percentage, maybe 90%
        grinding_fineness = 90 + 2 * chrono.ChFunction_Sine().Get_y(current_time / 1500) + random.uniform(-1, 1)
        data[self.grinding_fineness_sensor_id] = grinding_fineness

        # CO in Exhaust Gas (simulated, conceptual)
        # Critical value: < 0.1%. Let's fluctuate around good values, maybe occasional spikes
        co_gas = 0.05 + 0.02 * chrono.ChFunction_Sine().Get_y(current_time / 100)
        if current_time % 1000 < 50: # Simulate an occasional spike
            co_gas += 0.15
        co_gas += random.uniform(-0.01, 0.01)
        data[self.co_gas_sensor_id] = co_gas

        # NOx in Exhaust Gas (simulated, conceptual)
        # Higher fluctuations
        nox_gas = 300 + 50 * chrono.ChFunction_Sine().Get_y(current_time / 700) + random.uniform(-20, 20)
        data[self.nox_gas_sensor_id] = nox_gas

        # Mill Loading Level (simulated, conceptual)
        # Between 0 and 100%
        mill_loading = 75 + 10 * chrono.ChFunction_Sine().Get_y(current_time / 800) + random.uniform(-5, 5)
        data[self.mill_loading_sensor_id] = mill_loading

        return data

    def run_simulation(self, end_time=3600, timestep=0.01):
        # 7. Create a simulation loop
        global plant_id

        # Insert initial plant metadata
        plant_id = insert_plant_metadata("Cement Plant Alpha", "Industrial Park", 1)
        if plant_id is None:
            print("Failed to initialize plant metadata. Exiting.")
            return

        # Initialize Chrono Irrlicht viewer (optional, for visualization)
        application = None
        try:
            application = chronoirr.ChIrrApp(self.system, "Cement Plant Digital Twin", chronoirr.irr.dimension2d_u32(1024, 768), False, True)
            application.AddTypicalSky()
            application.AddTypicalLights()
            application.AddTypicalCamera(chronoirr.irr.core.vector3df(150, 50, 150),
                                         chronoirr.irr.core.vector3df(0, 0, 0)) # Camera position and target
            application.AssetBindAll()
            application.AssetUpdateAll()
            application.SetTimestep(timestep)

            # Simulation loop
            current_time = 0.0
            log_interval = 1.0 # Log every 1 second simulated time
            next_log_time = 0.0

            # Store last logged times for each sensor type
            last_logged_time = {
                "температура": current_time, # 1 раз в минуту (60 sec)
                "газоанализ": current_time,  # каждые 10 секунд
                "лаборатория": current_time  # 1 раз в час (3600 sec) -- currently not explicitly simulated
            }


            while application.Get='time' < end_time:
                application.Update()
                self.system.DoStepDynamics(timestep)

                current_time = self.system.GetChTime()
                timestamp = datetime.datetime.now(datetime.timezone.utc) # Use actual time for database

                # Collect and log sensor data based on frequency
                sensor_data = self.get_sensor_data(current_time)

                for sensor_chrono_id, value in sensor_data.items():
                    sensor_type = None
                    # Find sensor_type from sensor_metadata_map using sensor_chrono_id
                    # This is a bit indirect, might need to store sensor_type in the map directly
                    for db_id, chrono_id in sensor_metadata_map.items():
                        if chrono_id == sensor_chrono_id:
                            conn_temp = None
                            try:
                                conn_temp = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD)
                                cur_temp = conn_temp.cursor()
                                cur_temp.execute("SELECT sensor_type FROM sensor_metadata WHERE sensor_id = %s;", (sensor_chrono_id,))
                                res = cur_temp.fetchone()
                                if res:
                                    sensor_type = res[0]
                                break
                            except psycopg2.Error as e:
                                print(f"Error fetching sensor type: {e}")
                            finally:
                                if conn_temp:
                                    cur_temp.close()
                                    conn_temp.close()
                    
                    if sensor_type is None:
                        # Fallback for conceptual sensors without direct DB entries yet
                        if sensor_chrono_id == self.kiln_temp_sensor_id: sensor_type = "температура"
                        elif sensor_chrono_id == self.cyclone_draft_sensor_id: sensor_type = "разрежение"
                        elif sensor_chrono_id == self.co_gas_sensor_id or sensor_chrono_id == self.nox_gas_sensor_id: sensor_type = "газоанализ"
                        elif sensor_chrono_id == self.grinding_fineness_sensor_id: sensor_type = "тонкость помола"
                        elif sensor_chrono_id == self.mill_loading_sensor_id: sensor_type = "уровень загрузки"

                    perform_log = False
                    if sensor_type == "температура" and (current_time - last_logged_time["температура"]) >= 60.0:
                        perform_log = True
                        last_logged_time["температура"] = current_time
                    elif sensor_type == "газоанализ" and (current_time - last_logged_time["газоанализ"]) >= 10.0:
                        perform_log = True
                        last_logged_time["газоанализ"] = current_time
                    elif sensor_type not in ["температура", "газоанализ"]: # Log other sensors at log_interval for now
                        if (current_time - next_log_time) >= log_interval:
                            perform_log = True

                    if perform_log:
                        log_plant_data(timestamp, value, sensor_chrono_id)
                        # Optionally print for debugging
                        # print(f"Time: {current_time:.2f}, Sensor {sensor_chrono_id} ({sensor_type}): {value:.2f}")

                if (current_time - next_log_time) >= log_interval:
                    next_log_time = current_time + log_interval

                if not application.Get_Running(): # Allow closing the window to stop simulation
                    break

        except Exception as e:
            print(f"An error occurred during simulation: {e}")
        finally:
            if application:
                application.Clear()
                del application
            print("Simulation finished.")

def main():
    # Setup database
    create_database_schema()

    # Run simulation
    simulation = CementPlantSimulation()
    simulation.run_simulation(end_time=3000.0) # Run for 3000 simulated seconds

if __name__ == "__main__":
    main()