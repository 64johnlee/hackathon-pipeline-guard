FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml LICENSE README.md ./
COPY pipelineguard/ pipelineguard/
RUN pip install --no-cache-dir -e ".[web,vertex]"

# Cloud Run sets PORT; fall back to 8080
ENV PORT=8080

# Auth: set GEMINI_API_KEY (AI Studio) — required
# MCP mode: bundled pipeline MCP (stdio subprocess) +
#           official GitLab MCP (gitlab.com/api/v4/mcp, HTTP)
CMD exec pipelineguard serve \
    --host 0.0.0.0 \
    --port "${PORT}"
