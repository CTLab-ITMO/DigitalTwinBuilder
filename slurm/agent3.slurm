#!/bin/bash
#SBATCH --job-name=dt_a3
#SBATCH --time=08:00:00
#SBATCH --partition=gpu
#SBATCH --exclude=turing,laplas,midas,mars
#SBATCH --gres=gpu:1
#SBATCH --mem=20G
#SBATCH --output=logs/digital_twin_%j.out
#SBATCH --error=logs/digital_twin_%j.err

.venv/bin/python src/digital_twin_builder/agents/digital_twin_agent.py

