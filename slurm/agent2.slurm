#!/bin/bash
#SBATCH --job-name=dt_a2
#SBATCH --time=48:00:00
#SBATCH --partition=gpu
#SBATCH --exclude=turing,laplas,nike
#SBATCH --gres=gpu:1
#SBATCH --mem=10G
#SBATCH --output=logs/digital_twin_%j.out
#SBATCH --error=logs/digital_twin_%j.err

.venv/bin/python src/digital_twin_builder/agents/database_agent.py

