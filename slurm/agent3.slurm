#!/bin/bash
#SBATCH --job-name=dt_a3
#SBATCH --time=48:00:00
#SBATCH --partition=gpu
#SBATCH --exclude=turing,laplas,midas,mars
#SBATCH --qos=high_gpu
#SBATCH --nodes=1
#SBATCH --gpus-per-task=2
#SBATCH --gres=gpu:2
#SBATCH --mem=110G
#SBATCH --output=logs/digital_twin_%j.out
#SBATCH --error=logs/digital_twin_%j.err

.venv/bin/python src/digital_twin_builder/agents/digital_twin_agent.py

