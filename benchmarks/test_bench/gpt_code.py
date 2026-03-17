import pychrono.core as chrono
import pychrono.irrlicht as irr
import psycopg2
from datetime import datetime
import random
import sys
import time

# ----------------------------
# DATABASE CONFIGURATION
# ----------------------------
DB_SETTINGS = {
    "dbname": "cement_plant_db",
    "user": "plant_user",
    "password": "plant_password",
    "host": "localhost",
    "port": "5432"
}

# ----------------------------
# CONNECT TO DATABASE
# ----------------------------
def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        conn.autocommit = True
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        sys.exit(1)

# ----------------------------
# INSERT SENSOR DATA
# ----------------------------
def insert_sensor_data(conn, timestamp, value, sensor_id, plant_id):
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO plant_data (timestamp, value, sensor_id, plant_id)
                   VALUES (%s, %s, %s, %s)""",
                (timestamp, value, sensor_id, plant_id)
            )
    except Exception as e:
        print(f"Error inserting data: {e}")

# ----------------------------
# INITIALIZE CHRONO SYSTEM
# ----------------------------
sys = chrono.ChSystemNSC()
sys.Set_G_acc(chrono.ChVectorD(0, -9.81, 0))

# ----------------------------
# MATERIAL PROPERTIES
# ----------------------------
steel = chrono.ChMaterialSurfaceNSC()
steel.SetFriction(0.6)
steel.SetRestitution(0.1)

refractory = chrono.ChMaterialSurfaceNSC()
refractory.SetFriction(0.5)
refractory.SetRestitution(0.05)

# ----------------------------
# CREATE EQUIPMENT
# ----------------------------

def create_equipment(sys):
    equipment = {}

    # Crusher
    crusher = chrono.ChBodyEasyBox(2, 1, 1, 2500, True, True, steel)
    crusher.SetPos(chrono.ChVectorD(0, 0, 0))
    sys.Add(crusher)
    equipment["crusher"] = crusher

    # Raw mill
    raw_mill = chrono.ChBodyEasyCylinder(0.5, 2, 2500, True, True, steel)
    raw_mill.SetPos(chrono.ChVectorD(5, 0, 0))
    sys.Add(raw_mill)
    equipment["raw_mill"] = raw_mill

    # Rotary kiln
    kiln = chrono.ChBodyEasyCylinder(1.5, 10, 5000, True, True, refractory)
    kiln.SetPos(chrono.ChVectorD(12, 0, 0))
    sys.Add(kiln)
    equipment["kiln"] = kiln

    # Clinker cooler
    cooler = chrono.ChBodyEasyBox(4, 1, 2, 2000, True, True, steel)
    cooler.SetPos(chrono.ChVectorD(20, 0, 0))
    sys.Add(cooler)
    equipment["cooler"] = cooler

    # Cement mill
    cement_mill = chrono.ChBodyEasyCylinder(0.7, 3, 2500, True, True, steel)
    cement_mill.SetPos(chrono.ChVectorD(28, 0, 0))
    sys.Add(cement_mill)
    equipment["cement_mill"] = cement_mill

    # Silos
    silos = chrono.ChBodyEasyCylinder(2, 6, 1000, True, True, steel)
    silos.SetPos(chrono.ChVectorD(36, 0, 0))
    sys.Add(silos)
    equipment["silos"] = silos

    return equipment

equipment = create_equipment(sys)

# ----------------------------
# DEFINE JOINTS / CONSTRAINTS
# ----------------------------
joint1 = chrono.ChLinkLockLock()
joint1.Initialize(equipment["crusher"], equipment["raw_mill"], chrono.ChCoordsysD(chrono.ChVectorD(2.5, 0, 0)))
sys.AddLink(joint1)

joint2 = chrono.ChLinkLockLock()
joint2.Initialize(equipment["raw_mill"], equipment["kiln"], chrono.ChCoordsysD(chrono.ChVectorD(8.5, 0, 0)))
sys.AddLink(joint2)

joint3 = chrono.ChLinkLockLock()
joint3.Initialize(equipment["kiln"], equipment["cooler"], chrono.ChCoordsysD(chrono.ChVectorD(16, 0, 0)))
sys.AddLink(joint3)

joint4 = chrono.ChLinkLockLock()
joint4.Initialize(equipment["cooler"], equipment["cement_mill"], chrono.ChCoordsysD(chrono.ChVectorD(24, 0, 0)))
sys.AddLink(joint4)

joint5 = chrono.ChLinkLockLock()
joint5.Initialize(equipment["cement_mill"], equipment["silos"], chrono.ChCoordsysD(chrono.ChVectorD(32, 0, 0)))
sys.AddLink(joint5)

# ----------------------------
# SIMULATION PARAMETERS
# ----------------------------
timestep = 0.01
end_time = 10.0  # seconds for demo
current_time = 0.0

# Connect to database
conn = get_db_connection()

# ----------------------------
# SIMULATION LOOP
# ----------------------------
try:
    while current_time < end_time:
        sys.DoStepDynamics(timestep)

        # Simulated sensor readings
        temp_in_kiln = random.uniform(1450, 1480)
        vacuum_in_cyclone = random.uniform(-50, -80)
        fineness = random.uniform(3000, 4000)
        co_conc = random.uniform(0.05, 0.09)
        mill_load = random.uniform(70, 95)

        timestamp = datetime.now()

        # Sensor IDs are placeholders
        insert_sensor_data(conn, timestamp, temp_in_kiln, 1, 1)
        insert_sensor_data(conn, timestamp, vacuum_in_cyclone, 2, 1)
        insert_sensor_data(conn, timestamp, fineness, 3, 1)
        insert_sensor_data(conn, timestamp, co_conc, 4, 1)
        insert_sensor_data(conn, timestamp, mill_load, 5, 1)

        current_time += timestep

        # Optional: slow down loop to simulate real-time capture
        time.sleep(0.1)

except KeyboardInterrupt:
    print("Simulation interrupted by user")

except Exception as e:
    print(f"Error during simulation: {e}")

finally:
    if conn:
        conn.close()
    print("Simulation completed and database connection closed.")