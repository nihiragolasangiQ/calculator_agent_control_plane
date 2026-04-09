#!/bin/bash
# =============================================================================
# startup.sh — Entry point for the calculator agent container
# Reads RUN_MODE from environment and starts the appropriate mode
# =============================================================================

echo "🚀 Starting Calculator Agent..."
echo "   RUN_MODE : ${RUN_MODE:-ui}"
echo "   MODEL    : ${GOOGLE_API_KEY:+set}"

# default to ui if RUN_MODE not set
RUN_MODE=${RUN_MODE:-ui}

if [ "$RUN_MODE" = "ui" ]; then
    echo "🌐 Starting ADK Web UI on port 8000..."
    adk web /app --port 8000 --host 0.0.0.0

elif [ "$RUN_MODE" = "terminal" ]; then
    echo "💻 Starting in terminal mode..."
    python -m calculator_agent.agent_from_manifest

else
    echo "❌ Unknown RUN_MODE: $RUN_MODE"
    echo "   Valid options: ui | terminal"
    exit 1
fi