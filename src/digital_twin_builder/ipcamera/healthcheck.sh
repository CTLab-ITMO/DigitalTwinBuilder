#!/bin/bash

RESULT=$(ls /app/src/digital_twin_builder/ipcamera/python | grep *.so)

if [ -z "$RESULT" ]; then
    echo "Healthcheck failed"
    exit 1
fi

echo "Healthcheck passed"
exit 0