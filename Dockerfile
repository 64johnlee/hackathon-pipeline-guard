FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml LICENSE README.md ./
COPY pipelineguard/ pipelineguard/
RUN pip install --no-cache-dir -e ".[web,vertex]"

# Cloud Run sets PORT; fall back to 8080
ENV PORT=8080

# Auth: set GEMINI_API_KEY (AI Studio) or GCP_PROJECT + VERTEX_FLAG=--vertex (Vertex AI)
# Always uses --direct (no Node.js / MCP server in container)
CMD exec pipelineguard serve \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --direct \
    ${VERTEX_FLAG:-}
