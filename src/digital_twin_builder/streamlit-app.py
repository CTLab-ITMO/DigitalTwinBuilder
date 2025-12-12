# streamlit_app.py
import streamlit as st
import requests
import time
from datetime import datetime

# Configuration
API_URL = "http://localhost:8000"  # Change to your API URL

st.set_page_config(page_title="LLM Agent Control", layout="wide")

# Initialize session state
if 'tasks' not in st.session_state:
    st.session_state.tasks = []

# Helper functions
def submit_task(agent_id, prompt, params):
    """Submit task to API"""
    try:
        response = requests.post(
            f"{API_URL}/tasks",
            json={
                "agent_id": agent_id,
                "prompt": prompt,
                "params": params,
                "priority": 5
            },
            timeout=10
        )
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"API Error: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None

def get_task_status(task_id):
    """Get task status from API"""
    try:
        response = requests.get(f"{API_URL}/tasks/{task_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None

def get_agent_status(agent_id):
    """Get agent status from API"""
    try:
        response = requests.get(f"{API_URL}/agents/{agent_id}/status", timeout=5)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return {"status": "offline"}

# Main UI
st.title("🤖 LLM Agent Control Panel")

# Sidebar - Agent Status
with st.sidebar:
    st.header("Agent Status")
    
    for agent_id in [1, 2, 3]:
        status = get_agent_status(agent_id)
        status_color = {
            "idle": "🟢",
            "busy": "🟡",
            "offline": "🔴"
        }.get(status.get("status", "offline"), "⚪")
        
        st.markdown(f"**Agent {agent_id}** {status_color}")
        st.caption(f"Status: {status.get('status', 'offline')}")

# Main Area - Task Submission
col1, col2 = st.columns([2, 1])

with col1:
    st.header("Submit Task")
    
    with st.form("task_form"):
        agent_id = st.selectbox("Agent", [1, 2, 3], key="agent_select")
        prompt = st.text_area("Prompt", height=150, 
            placeholder="Enter your prompt here...")
        
        with st.expander("Parameters"):
            temperature = st.slider("Temperature", 0.0, 2.0, 0.7, 0.1)
            max_tokens = st.number_input("Max Tokens", 100, 4000, 1000)
        
        submitted = st.form_submit_button("Submit")
        
        if submitted and prompt:
            params = {
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            task_info = submit_task(agent_id, prompt, params)
            if task_info:
                st.success(f"Task submitted! ID: {task_info['task_id'][:8]}...")
                st.session_state.tasks.append(task_info['task_id'])

with col2:
    st.header("Queue Status")
    
    for agent_id in [1, 2, 3]:
        try:
            response = requests.get(f"{API_URL}/queue/{agent_id}", timeout=5)
            if response.status_code == 200:
                queue = response.json()
                with st.expander(f"Agent {agent_id}"):
                    st.metric("Pending", queue["pending_count"])
                    if queue["active_task"]:
                        st.caption(f"Active: {queue['active_task']['id'][:8]}...")
        except:
            st.caption(f"Agent {agent_id}: Unavailable")

# Task Monitor
st.header("Task Monitor")

if st.session_state.tasks:
    # Refresh button
    if st.button("🔄 Refresh", type="secondary"):
        st.rerun()
    
    # Display tasks
    for task_id in st.session_state.tasks[-5:]:  # Last 5 tasks
        task = get_task_status(task_id)
        
        if task:
            with st.container():
                col1, col2, col3 = st.columns([3, 1, 1])
                
                with col1:
                    st.text(f"ID: {task_id[:12]}...")
                    st.caption(f"Prompt: {task['prompt'][:100]}...")
                    st.caption(f"Created: {task['created_at'][:19]}")
                
                with col2:
                    status = task['status']
                    if status == 'completed':
                        st.success("✅ Done")
                    elif status == 'processing':
                        st.warning("🔄 Processing")
                    elif status == 'pending':
                        st.info("⏳ Pending")
                    else:
                        st.error("❌ Failed")
                
                with col3:
                    if status == 'completed':
                        if st.button("View", key=f"view_{task_id}"):
                            st.text_area("Result", task.get('result', 'No result'), 
                                       height=200, key=f"result_{task_id}")
                    elif status == 'failed':
                        st.error(task.get('error', 'Unknown error'))
                
                st.divider()
else:
    st.info("No tasks submitted yet.")

# Auto-refresh option
if st.checkbox("Auto-refresh every 5 seconds"):
    time.sleep(5)
    st.rerun()
