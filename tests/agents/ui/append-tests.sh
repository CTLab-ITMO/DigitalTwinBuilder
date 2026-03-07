#!/bin/bash

for i in $(seq 8 8);
do
    echo "testing tests/agents/ui/jsons/${i}.json"
    ./.venv/bin/python tests/agents/ui/llm-responder.py tests/agents/ui/jsons/${i}.json
done

