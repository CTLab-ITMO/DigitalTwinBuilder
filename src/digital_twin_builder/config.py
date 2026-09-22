"""
Configuration module for loading environment variables.
This module loads settings from .env file and provides them to the application.
"""
import os
import sys
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

# OpenRouter Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-coder-30b-a3b-instruct")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "DigitalTwinBuilder")
# Comma-separated upstream providers to exclude from routing. Defaults to
# Novita, which intermittently answers 200 with content=null (the text is
# generated and billed but never serialized). Set to empty to allow all.
OPENROUTER_IGNORE_PROVIDERS = os.getenv("OPENROUTER_IGNORE_PROVIDERS", "Novita")

# Agents configuration
UI_AGENT_INDEX = int(os.getenv("UI_AGENT_INDEX", "0"))
DB_AGENT_INDEX = int(os.getenv("DB_AGENT_INDEX", "1"))
DT_AGENT_INDEX = int(os.getenv("DT_AGENT_INDEX", "2"))
UI_AGENT_MODEL = os.getenv("UI_AGENT_MODEL", "")
DB_AGENT_MODEL = os.getenv("DB_AGENT_MODEL", "")
DT_AGENT_MODEL = os.getenv("DT_AGENT_MODEL", "")

# DES (SimPy) model execution. The generated model is run by the interpreter in
# DES_PYTHON, which must have simpy installed; DES_REPAIR_ATTEMPTS is how many
# corrected programs the DES agent may be asked for after a failed execution
# (0 disables the repair turn and returns the first program as-is).
DES_PYTHON = os.getenv("DES_PYTHON", sys.executable)
DES_EXEC_TIMEOUT_S = int(os.getenv("DES_EXEC_TIMEOUT_S", "900"))
DES_REPAIR_ATTEMPTS = int(os.getenv("DES_REPAIR_ATTEMPTS", "3"))
# How long one DES turn may take before it is abandoned. The DT agent runs a
# local model with thinking on, so a single turn is slow.
DES_GEN_TIMEOUT_S = int(os.getenv("DES_GEN_TIMEOUT_S", "900"))
DES_MAX_TOKENS = int(os.getenv("DES_MAX_TOKENS", "8000"))

# DB (PostgreSQL) schema validation. The generated schema is checked
# structurally — parse-only, no server is contacted — and DB_REPAIR_ATTEMPTS is
# how many corrected schemas the DB agent may be asked for after a reply that
# does not hold together (0 disables the repair turn and keeps the first reply).
DB_REPAIR_ATTEMPTS = int(os.getenv("DB_REPAIR_ATTEMPTS", "3"))

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
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_MODEL",
    "OPENROUTER_SITE_URL",
    "OPENROUTER_APP_NAME",
    "OPENROUTER_IGNORE_PROVIDERS",
    "UI_AGENT_INDEX",
    "DB_AGENT_INDEX",
    "DT_AGENT_INDEX",
    "UI_AGENT_MODEL",
    "DB_AGENT_MODEL",
    "DT_AGENT_MODEL",
    "DES_PYTHON",
    "DES_EXEC_TIMEOUT_S",
    "DES_REPAIR_ATTEMPTS",
    "DES_GEN_TIMEOUT_S",
    "DES_MAX_TOKENS",
    "DB_REPAIR_ATTEMPTS",
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
