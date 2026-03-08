#!/bin/bash
#SBATCH --job-name=dt_a2
#SBATCH --time=08:00:00
#SBATCH --partition=gpu
#SBATCH --nodelist=kali
#SBATCH --gres=gpu:1
#SBATCH --mem=20G
#SBATCH --output=logs/digital_twin_%j.out
#SBATCH --error=logs/digital_twin_%j.err

.venv/bin/python src/digital_twin_builder/DTlibrary/agents/database_agent.py --api-url=http://188.119.67.226:8000 --agent-id=2 --model=./models/SmolLM3-3B/

