#!/bin/bash

echo "test,json_score,sql_score" > tests/agents/ui/scores.csv
for i in $(seq 1 10);
do
    echo "testing tests/agents/ui/jsons/${i}.json"
    ./.venv/bin/python tests/agents/ui/llm-responder.py tests/agents/ui/jsons/${i}.json
done

