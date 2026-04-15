#!/bin/bash
# startup.sh — reads RUN_MODE from env and launches the right process
# RUN_MODE=ui       → adk web (default)
# RUN_MODE=terminal → interactive REPL

set -e

RUN_MODE=${RUN_MODE:-ui}

echo "Starting Agent Control Plane (RUN_MODE=${RUN_MODE})..."

if [ "$RUN_MODE" = "terminal" ]; then
    exec python -m orchestrator.agent_from_manifest #run locally
else
    exec adk web /app --port 8000 --host 0.0.0.0
fi
