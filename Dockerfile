FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml LICENSE README.md ./
COPY pipelineguard/ pipelineguard/
COPY entrypoint.sh ./
RUN pip install --no-cache-dir -e ".[web,vertex]" && chmod +x entrypoint.sh

# Cloud Run sets PORT; fall back to 8080
ENV PORT=8080

# Auth: set GEMINI_API_KEY (AI Studio), OR set VERTEX_FLAG="--vertex --gcp-project <id>"
# for Vertex AI (deploy_cloudrun.sh sets VERTEX_FLAG automatically when no API key
# is provided). VERTEX_FLAG is empty in AI Studio mode, so this expands to nothing.
# On non-GCP hosts (e.g. a Hugging Face Space) there is no metadata server for
# Vertex ADC, so set GOOGLE_CREDENTIALS_JSON to a service-account key and the
# entrypoint will materialise it (see entrypoint.sh).
# MCP mode: bundled pipeline MCP (stdio subprocess) +
#           official GitLab MCP (gitlab.com/api/v4/mcp, HTTP)
CMD ["./entrypoint.sh"]
