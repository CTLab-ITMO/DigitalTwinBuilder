#!/bin/bash
#SBATCH --job-name=digital_twin
#SBATCH --time=01:00:00
#SBATCH --partition=main
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=10
#SBATCH --mem=20G
#SBATCH --output=logs/digital_twin_%j.out
#SBATCH --error=logs/digital_twin_%j.err

/usr/bin/python3 agent.py --api-url=http://92.100.72.33:8000 --agent-id=2
