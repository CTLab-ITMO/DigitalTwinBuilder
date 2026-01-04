#!/bin/bash
#SBATCH --job-name=digital_twin
#SBATCH --time=08:00:00
#SBATCH --partition=gpu
#SBATCH --nodelist=kali
#SBATCH --gres=gpu:1
#SBATCH --ntasks=1
#SBATCH --mem=20G
#SBATCH --output=logs/digital_twin_%j.out
#SBATCH --error=logs/digital_twin_%j.err

.venv/bin/python src/digital_twin_builder/DTlibrary/agents/user_interaction_agent.py --api-url=http://92.100.72.33:8000 --agent-id=1 --model=./models/SmolLM3-3B
# .venv/bin/python src/digital_twin_builder/DTlibrary/agents/database_agent.py --api-url=http://92.100.72.33:8000 --agent-id=2 --model=./models/Qwen-3-4b-Text_to_SQL/

