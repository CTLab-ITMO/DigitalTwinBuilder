#!/bin/bash

# Check for input parameter
if [ -z "$1" ]; then
    echo "Usage: ./monitor_agent.sh <index>"
    exit 1
fi

INDEX=$1
TARGET_NAME="dt_a${INDEX}"

# Outer loop: Keeps the script running even if jobs finish or are cancelled
while true; do
    JOB_ID=""

    echo "Searching for job: $TARGET_NAME..."
    
    # Discovery Loop: Wait until the job exists
    while [ -z "$JOB_ID" ]; do
        JOB_ID=$(squeue -p gpu -h -o "%i" --name="$TARGET_NAME" | head -n 1)
        
        if [ -z "$JOB_ID" ]; then
            sleep 10
        fi
    done

    echo "Found Job ID: $JOB_ID. Monitoring..."
    LOG_FILE="logs/digital_twin_${JOB_ID}.err"

    # Monitor Loop: Manually implement 'watch' and check job status
    while true; do
        # 1. Clear screen to mimic 'watch' behavior
        clear
        echo "Monitoring: $TARGET_NAME (ID: $JOB_ID) | Refresh: 10s"
        echo "Log: $LOG_FILE"
        echo "------------------------------------------------------------"

        # 2. Display the tail of the log file
        if [ -f "$LOG_FILE" ]; then
            tail -n 10 "$LOG_FILE"
        else
            echo "[Waiting for log file to be created...]"
        fi

        echo "------------------------------------------------------------"

        # 3. Check Job Status
        # %t returns the state (R=Running, PD=Pending, CG=Completing, etc.)
        STATUS=$(squeue -h -j "$JOB_ID" -o "%t" 2>/dev/null)

        # 4. Logic check: If job is gone (empty status) or Completing (CG)
        if [[ -z "$STATUS" || "$STATUS" == "CG" ]]; then
            echo "Job $JOB_ID has ended, been cancelled, or is completing (Status: ${STATUS:-NONE})."
            echo "Returning to search mode..."
            sleep 3
            break # Exit the Monitor Loop to go back to Discovery
        fi

        # 5. Wait for the next interval
        sleep 10
    done
done
