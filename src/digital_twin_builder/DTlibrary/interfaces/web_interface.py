import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from cores.database import DatabaseManager
from cores.sensor_manager import SensorManager
import json
from agents.user_interaction_agent import UserInteractionAgent
from agents.database_agent import DatabaseAgent
from agents.digital_twin_agent import DigitalTwinAgent

class DigitalTwinInterface:
    def __init__(self):
        self.ui_agent = UserInteractionAgent()
        self.db_agent = DatabaseAgent()
        self.dt_agent = DigitalTwinAgent()
        self.sensor_manager = None
        self.db_manager = None
        self.setup_ui()

    def setup_ui(self):
        st.set_page_config(page_title="Digital Twin System", layout="wide")
        st.title("Digital Twin Creation System")
        
        self.tab1, self.tab2, self.tab3, self.tab4 = st.tabs([
            "User Interview", 
            "Database Configuration", 
            "Digital Twin",
            "Sensor Dashboard"
        ])
        
        with self.tab1:
            self.setup_interview_tab()
        with self.tab2:
            self.setup_database_tab()
        with self.tab3:
            self.setup_twin_tab()
        with self.tab4:
            self.setup_sensor_tab()

    def setup_interview_tab(self):
        st.header("Enterprise Information Collection")
        employee_id = st.text_input("Employee ID")
        
        if st.button("Start Interview"):
            with st.spinner("Conducting interview..."):
                try:
                    interview_result = self.ui_agent.conduct_interview(employee_id)
                    st.session_state.interview_result = interview_result
                    st.success("Interview completed!")
                    st.json(interview_result)
                except Exception as e:
                    st.error(f"Interview failed: {str(e)}")

    def setup_database_tab(self):
        st.header("Database Configuration")
        
        if 'interview_result' not in st.session_state:
            st.warning("Please complete the interview first")
            return
            
        db_type = st.selectbox("Preferred Database Type", ["PostgreSQL", "MongoDB", ""])
        
        if st.button("Design Database"):
            with st.spinner("Designing database..."):
                try:
                    app_description = json.dumps(st.session_state.interview_result)
                    db_schema = self.db_agent.design_database(app_description, db_type)
                    st.session_state.db_schema = db_schema
                    st.success("Database designed!")
                    st.json(db_schema)
                except Exception as e:
                    st.error(f"Database design failed: {str(e)}")

    def setup_twin_tab(self):
        st.header("Digital Twin Configuration")
        
        if 'db_schema' not in st.session_state:
            st.warning("Please complete database design first")
            return
        
        mode = st.radio("Sensor Mode", ["Simulation", "Real Hardware"], index=0)
        sensor_mode = 'sim' if mode == "Simulation" else 'real'
            
        if st.button("Configure Digital Twin"):
            with st.spinner("Configuring digital twin..."):
                try:
                    system_description = json.dumps(st.session_state.interview_result)
                    twin_config = self.dt_agent.configure_twin(
                        system_description,
                        st.session_state.db_schema,
                        {"sensors": ["temperature", "pressure", "vibration", "level", "wear", "rfid"]}
                    )
                    st.session_state.twin_config = twin_config
                    st.success("Digital twin configured!")
                    st.json(twin_config)
                    
                    # Initialize database and sensors
                    self.db_manager = DatabaseManager(
                        dbname="digital_twin",
                        user="postgres",
                        password="password"
                    )
                    self.db_manager.create_sensor_tables()
                    
                    self.sensor_manager = SensorManager(mode=sensor_mode)
                    self.sensor_manager.start()
                    st.session_state.sensor_running = True
                    st.session_state.sensor_mode = sensor_mode
                except Exception as e:
                    st.error(f"Digital twin configuration failed: {str(e)}")
        
        if st.button("Stop Sensor Simulation", disabled=not st.session_state.get('sensor_running', False)):
            self.sensor_manager.stop()
            if self.db_manager:
                self.db_manager.close()
            st.session_state.sensor_running = False
            st.success("Sensor simulation stopped")

    def setup_sensor_tab(self):
        st.header("Real-time Sensor Dashboard")
        
        if not st.session_state.get('sensor_running', False):
            st.warning("Please start the digital twin first")
            return
        
        # Toggle between simulation and real mode
        current_mode = st.session_state.get('sensor_mode', 'sim')
        new_mode = st.radio("Sensor Mode", 
                           ["Simulation", "Real Hardware"],
                           index=0 if current_mode == 'sim' else 1)
        
        if (new_mode == "Simulation" and current_mode != 'sim') or \
           (new_mode == "Real Hardware" and current_mode == 'sim'):
            self.sensor_manager.set_mode('sim' if new_mode == "Simulation" else 'real')
            st.session_state.sensor_mode = 'sim' if new_mode == "Simulation" else 'real'
            st.experimental_rerun()
        
        # Display real-time sensor data
        data = self.sensor_manager.get_data()
        if data:
            self.db_manager.store_sensor_data(data)
            
            # Convert to DataFrame for display
            sensor_df = pd.DataFrame.from_dict(data["sensor_data"], orient='index', columns=['value'])
            st.dataframe(sensor_df)
            
            # Plot sensor data
            fig = px.line(
                sensor_df, 
                y="value",
                title="Real-time Sensor Values",
                labels={"index": "Sensor", "value": "Value"}
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # Show historical data
            time_range = st.selectbox("Time Range", ["5 minutes", "15 minutes", "1 hour"])
            minutes = 5 if time_range == "5 minutes" else 15 if time_range == "15 minutes" else 60
            self.display_historical_data(minutes)

    def display_historical_data(self, minutes):
        """Display historical sensor data from the database"""
        try:
            time_threshold = datetime.now() - timedelta(minutes=minutes)
            query = """SELECT sensor_type, AVG(value) as avg_value 
                        FROM sensor_data 
                        WHERE timestamp >= %s AND value IS NOT NULL
                        GROUP BY sensor_type"""
            self.db_manager.cursor.execute(query, (time_threshold,))
            results = self.db_manager.cursor.fetchall()
            
            if results:
                hist_df = pd.DataFrame(results, columns=["Sensor", "Average Value"])
                st.subheader(f"Average Values (Last {minutes} minutes)")
                st.dataframe(hist_df)
                
                fig = px.bar(
                    hist_df,
                    x="Sensor",
                    y="Average Value",
                    title=f"Sensor Averages (Last {minutes} minutes)"
                )
                st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Failed to fetch historical data: {str(e)}")

interface = DigitalTwinInterface()