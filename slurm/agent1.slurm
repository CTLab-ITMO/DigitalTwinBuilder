#!/bin/bash
#SBATCH --job-name=dt_a1
#SBATCH --time=48:00:00
#SBATCH --partition=gpu
#SBATCH --exclude=laplas,turing
#SBATCH --gres=gpu:1
#SBATCH --mem=20G
#SBATCH --output=logs/digital_twin_%j.out
#SBATCH --error=logs/digital_twin_%j.err

.venv/bin/python src/digital_twin_builder/agents/user_interaction_agent.py

