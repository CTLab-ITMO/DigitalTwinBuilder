import pychrono as chrono
import pychrono.sensor as chrono_sensor
import pychrono.irrlicht as chrono_irr
import sqlite3
import time
import random

# Initialize the Chrono system
system = chrono.ChSystemNSC()
system.Set_G_acc(chrono.ChVectorD(0, -9.81, 0))

# Create materials
steel_material = chrono.ChMaterialSurfaceNSC()
refractory_material = chrono.ChMaterialSurfaceNSC()

# Define equipment dimensions and properties
furnace_length = 10
furnace_radius = 1
mill_radius = 0.5
mill_length = 2

# Create physical bodies representing equipment
furnace = chrono.ChBodyEasyCylinder(furnace_radius, furnace_length, True, False)
furnace.SetMaterialSurface(refractory_material)
furnace.SetPos(chrono.ChVectorD(0, 0, 0))
system.AddBody(furnace)

mill = chrono.ChBodyEasyCylinder(mill_radius, mill_length, True, False)
mill.SetMaterialSurface(steel_material)
mill.SetPos(chrono.ChVectorD(12, 0, 0))
system.AddBody(mill)

# Define joints and constraints
furnace_joint = chrono.ChLinkLockRevolute()
furnace_joint.Initialize(furnace, system.Get_ground(), chrono.ChCoordsysD(chrono.ChVectorD(0, 0, 0), chrono.Q_from_AngAxis(0, chrono.VECT_Y)))
system.AddLink(furnace_joint)

# Set up sensors
temperature_sensor = chrono_sensor.ChSensorThermal()
temperature_sensor.AddRegion(furnace, chrono.ChVectorD(0, 0, 0), 1)
system.AddSensor(temperature_sensor)

# Connect to the database
conn = sqlite3.connect('plant_data.db')
cursor = conn.cursor()

# Create tables if they do not exist
cursor.execute('''
CREATE TABLE IF NOT EXISTS plant_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    value REAL NOT NULL,
    sensor_id INTEGER NOT NULL,
    plant_id INTEGER NOT NULL,
    FOREIGN KEY (sensor_id) REFERENCES sensor_metadata(id) ON DELETE CASCADE,
    FOREIGN KEY (plant_id) REFERENCES metadata(id) ON DELETE CASCADE
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS sensor_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_type TEXT NOT NULL,
    location TEXT NOT NULL,
    calibration_status BOOLEAN NOT NULL,
    sensor_id INTEGER UNIQUE NOT NULL
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_name TEXT NOT NULL,
    location TEXT NOT NULL,
    version INTEGER NOT NULL,
    last_updated DATETIME NOT NULL
)
''')

conn.commit()

# Simulation loop
simulation_time = 0
simulation_step = 0.01
simulation_duration = 60  # seconds

try:
    while simulation_time < simulation_duration:
        # Step the simulation forward in time
        system.DoStepDynamics(simulation_step)
        simulation_time += simulation_step

        # Collect sensor data
        temperature = temperature_sensor.GetTemperature()

        # Log data
        cursor.execute('INSERT INTO plant_data (timestamp, value, sensor_id, plant_id) VALUES (?, ?, ?, ?)',
                       (time.strftime('%Y-%m-%d %H:%M:%S'), temperature, 1, 1))
        conn.commit()

        # Print current state for debugging
        print(f'Time: {simulation_time:.2f}s, Temperature: {temperature:.2f}°C')

except Exception as e:
    print(f'An error occurred: {e}')

finally:
    # Proper cleanup
    conn.close()
    system.RemoveAll()