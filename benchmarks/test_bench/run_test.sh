#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  Cement Plant Digital Twin — Test Runner"
echo "============================================"
echo ""

if [ -f "requirements.txt" ]; then
    echo "Installing Python dependencies from requirements.txt"
    python3 -m pip install -r requirements.txt
    echo ""
fi

if [ $# -gt 0 ]; then
    python3 tests.py "$@"
else
    python3 tests.py
fi

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "All tests passed."
else
    echo "Some tests failed (exit code $EXIT_CODE)."
fi

exit $EXIT_CODE
