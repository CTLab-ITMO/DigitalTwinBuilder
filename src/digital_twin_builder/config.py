"""
Configuration module for loading environment variables.
This module loads settings from .env file and provides them to the application.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from the workspace root
env_path = ".env"
load_dotenv(dotenv_path=env_path)
# API Configuration
API_URL = os.getenv("API_URL", "http://188.119.67.226:8000")

# LLM Configuration
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# Agents configuration
UI_AGENT_INDEX = int(os.getenv("UI_AGENT_INDEX", "0"))
DB_AGENT_INDEX = int(os.getenv("DB_AGENT_INDEX", "1"))
DT_AGENT_INDEX = int(os.getenv("DT_AGENT_INDEX", "2"))
UI_AGENT_MODEL = os.getenv("UI_AGENT_MODEL", "")
DB_AGENT_MODEL = os.getenv("DB_AGENT_MODEL", "")
DT_AGENT_MODEL = os.getenv("DT_AGENT_MODEL", "")

# Database Configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "admin")
POSTGRES_DB = os.getenv("POSTGRES_DB", "llm_agents")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

# Grafana Configuration
GRAFANA_ADMIN_PASSWORD = os.getenv("GRAFANA_ADMIN_PASSWORD", "admin")
GRAFANA_ADMIN_USER = os.getenv("GRAFANA_ADMIN_USER", "admin")

# Application Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

__all__ = [
    "API_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "LLM_MODEL",
    "UI_AGENT_INDEX",
    "DB_AGENT_INDEX",
    "DT_AGENT_INDEX",
    "UI_AGENT_MODEL",
    "DB_AGENT_MODEL",
    "DT_AGENT_MODEL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "GRAFANA_ADMIN_PASSWORD",
    "GRAFANA_ADMIN_USER",
    "LOG_LEVEL",
    "DEBUG",
]
