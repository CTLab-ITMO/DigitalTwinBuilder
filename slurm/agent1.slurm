#!/bin/bash
#SBATCH --job-name=dt_a1
#SBATCH --time=48:00:00
#SBATCH --partition=gpu
#SBATCH --exclude=laplas,turing
#SBATCH --gres=gpu:1
#SBATCH --mem=20G
#SBATCH --output=logs/digital_twin_%j.out
#SBATCH --error=logs/digital_twin_%j.err

# The interview agent answers long prompts, and a long prompt's attention tensor
# is a large contiguous allocation. Without expandable segments the caching
# allocator cannot satisfy it from the scattered free blocks a previous turn
# left, and the turn dies with "tried to allocate N GiB ... Y GiB free" while
# the memory it needs is in fact there. Same setting the anomaly detector uses.
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

.venv/bin/python src/digital_twin_builder/agents/user_interaction_agent.py

