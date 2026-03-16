#!/bin/bash
#SBATCH --job-name=dt
#SBATCH --time=08:00:00
#SBATCH --partition=gpu
#SBATCH --exclude=turing,laplas,midas,mars
#SBATCH --ntasks=3
#SBATCH --gres=gpu:3
#SBATCH --mem=20G
#SBATCH --output=logs/digital_twin_%j.out
#SBATCH --error=logs/digital_twin_%j.err

#srun .venv/bin/python src/digital_twin_builder/DTlibrary/agents/user_interaction_agent.py &
#srun .venv/bin/python src/digital_twin_builder/DTlibrary/agents/database_agent.py &
# #srun .venv/bin/python src/digital_twin_builder/DTlibrary/agents/digital_twin_agent.py &

wait
