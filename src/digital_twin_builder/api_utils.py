"""
API utility functions for communicating with the agent backend.
Used by both streamlit-app and other agents.
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import logging
from .config import API_URL

logger = logging.getLogger(__name__)

# requests_session is initialized at module level
requests_session = None


def init_session():
    """Initialize requests session with retry strategy"""
    global requests_session
    requests_session = requests.Session()
    retry = Retry(connect=3, backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    requests_session.mount('http://', adapter)
    requests_session.mount('https://', adapter)
    return requests_session


def get_session():
    """Get or initialize the requests session"""
    global requests_session
    if requests_session is None:
        init_session()
    return requests_session


def submit_task(agent_id, conversation_id, params, conv_idx=0):
    """Submit task to API
    
    Args:
        agent_id: ID of the agent
        conversation_id: ID of the conversation
        params: Parameters for the task
        conv_idx: Conversation index for multi-turn tasks (default 0)
    
    Returns:
        dict: Response JSON or None if error
    """
    try:
        session = get_session()
        payload = {
            "agent_id": agent_id,
            "conv_idx": conv_idx,
            "conversation_id": conversation_id,
            "params": params,
            "priority": 5,
        }
        if conv_idx is not None:
            payload["conv_idx"] = conv_idx
            
        response = session.post(
            f"{API_URL}/tasks",
            json=payload,
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"API Error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
        return None


def add_message_to_conversation(conversation_id, role, content):
    """Add a message to a conversation
    
    Args:
        conversation_id: ID of the conversation
        role: Role of the message sender (system, user, assistant)
        content: Content of the message
    
    Returns:
        dict: Response JSON or None if error
    """
    try:
        session = get_session()
        response = session.post(
            f"{API_URL}/conversations/{conversation_id}/messages",
            params={
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
            },
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"API Error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
    return None


def get_task_status(task_id):
    """Get task status from API
    
    Args:
        task_id: ID of the task
    
    Returns:
        dict: Task status or None if error
    """
    try:
        session = get_session()
        response = session.get(f"{API_URL}/tasks/{task_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
    return None


def get_agent_status(agent_id):
    """Get agent status from API
    
    Args:
        agent_id: ID of the agent
    
    Returns:
        dict: Agent status or offline status if error
    """
    try:
        session = get_session()
        response = session.get(f"{API_URL}/agents/{agent_id}/status", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
    return {"status": "offline"}


def poll_task_result(task_id, max_poll=30):
    """Poll for task result until completion
    
    Args:
        task_id: ID of the task
        max_poll: Maximum number of polls (default 30, 1 poll per second)
    
    Returns:
        dict: Completed task or partial result if timeout
    """
    poll = 0
    while poll < max_poll:
        task = get_task_status(task_id)
        if task and task["status"] == "completed":
            return task
        else:
            time.sleep(1)
        poll += 1
    return {"task_id": task_id}


def create_new_conversation(session_id, agent_id, system_prompt):
    """Create a new conversation
    
    Args:
        session_id: ID of the session
        agent_id: ID of the agent
        system_prompt: System prompt for the conversation
    
    Returns:
        str: Conversation ID or None if error
    """
    try:
        session = get_session()
        response = session.post(
            f"{API_URL}/conversations",
            params={"session_id": session_id, "agent_id": agent_id},
        )
        if response.status_code == 200:
            conversation_id = response.json()["conversation_id"]
        else:
            logger.error(
                f"Failed to create conversation with agent {agent_id}, "
                f"error {response.status_code}"
            )
            return None
            
        response_message = add_message_to_conversation(
            conversation_id, "system", system_prompt
        )
        if response_message is not None:
            return conversation_id
        else:
            logger.error(
                f"Failed to add system prompt to conversation {conversation_id} "
                f"with agent {agent_id}"
            )
            return None
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
    return None


def create_new_session():
    """Create a new session
    
    Returns:
        str: Session ID or None if error
    """
    try:
        session = get_session()
        response = session.post(
            f"{API_URL}/sessions",
            params={"user_id": "streamlit_user", "title": "New Chat"},
        )
        if response.status_code == 200:
            session_id = response.json()["session_id"]
            return session_id
        else:
            logger.error(
                f"Failed to create session, error {response.status_code}"
            )
            return None
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
    return None
