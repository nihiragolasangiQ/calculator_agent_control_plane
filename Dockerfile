FROM python:3.11-slim

WORKDIR /app

# node is required for stdio MCP servers (e.g. npx firecrawl-mcp)
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.docker.txt .
RUN pip install --no-cache-dir -r requirements.docker.txt

COPY orchestrator/ ./orchestrator/
COPY startup.sh .
RUN chmod +x startup.sh

EXPOSE 8000
CMD ["./startup.sh"]
