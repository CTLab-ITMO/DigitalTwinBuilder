#!/bin/bash

squeue -h -o "%i %j" | awk '$2 ~ /^dt_a/ {print $1}' | xargs -r scancel
