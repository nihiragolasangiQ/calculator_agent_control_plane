# =============================================================================
# Dockerfile — Control Plane
# Base: Python 3.11 slim (stable for ADK)
# =============================================================================

FROM python:3.11-slim

# -----------------------------------------------------------------------------
# SYSTEM SETUP
# -----------------------------------------------------------------------------
WORKDIR /app

# install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------------
# DEPENDENCIES
# install python packages first (cached layer — only rebuilds if requirements change)
# -----------------------------------------------------------------------------
COPY requirements.docker.txt .
RUN pip install --no-cache-dir -r requirements.docker.txt

# -----------------------------------------------------------------------------
# CODE
# copy project files into container
# -----------------------------------------------------------------------------
COPY orchestrator/ ./orchestrator/

# -----------------------------------------------------------------------------
# STARTUP SCRIPT
# handles ui vs terminal mode
# -----------------------------------------------------------------------------
COPY startup.sh .
RUN chmod +x startup.sh

# expose port for adk web UI
EXPOSE 8000

# -----------------------------------------------------------------------------
# ENTRYPOINT
# startup.sh reads RUN_MODE and decides what to run
# -----------------------------------------------------------------------------
CMD ["./startup.sh"]