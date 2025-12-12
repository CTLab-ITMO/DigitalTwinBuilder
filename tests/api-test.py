# test_api.py
import requests
import time

API_URL = "http://localhost:8000"

def test_api():
    # Test health endpoint
    print("Testing health endpoint...")
    try:
        resp = requests.get(f"{API_URL}/health")
        print(f"Health: {resp.status_code} - {resp.json()}")
    except Exception as e:
        print(f"Health check failed: {e}")
        return
    
    # Submit a test task
    print("\nSubmitting test task...")
    task_data = {
        "agent_id": 1,
        "prompt": "Hello, world!",
        "params": {"temperature": 0.7},
        "priority": 5
    }
    
    resp = requests.post(f"{API_URL}/tasks", json=task_data)
    if resp.status_code == 200:
        task_info = resp.json()
        print(f"Task created: {task_info}")
        task_id = task_info["task_id"]
        
        # Check task status
        print(f"\nChecking task status...")
        resp = requests.get(f"{API_URL}/tasks/{task_id}")
        print(f"Task status: {resp.json()}")
        
        # Check agent status
        print(f"\nChecking agent status...")
        resp = requests.get(f"{API_URL}/agents/1/status")
        print(f"Agent status: {resp.json()}")
        
        # Check queue
        print(f"\nChecking queue...")
        resp = requests.get(f"{API_URL}/queue/1")
        print(f"Queue: {resp.json()}")
        
    else:
        print(f"Task creation failed: {resp.status_code} - {resp.text}")

if __name__ == "__main__":
    # Wait for API to start
    time.sleep(2)
    test_api()
