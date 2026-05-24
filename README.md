# PipelineGuard

> AI-powered GitLab CI pipeline diagnostics using Gemini 2.0 Flash + GitLab MCP Server

PipelineGuard watches your GitLab CI pipelines. When one fails, it:

1. **Fetches** job logs via the GitLab MCP server
2. **Analyzes** root cause with Gemini 2.0 Flash (not just "build failed" — the *exact* reason)
3. **Proposes** a targeted fix with a unified diff
4. **Comments** the findings on the associated merge request

Built for the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com) — GitLab track.

---

## Architecture

```
User / CI Webhook
      │
      ▼
┌─────────────────────────────────────────────────┐
│  PipelineGuardAgent  (pipelineguard/agent.py)   │
│                                                 │
│  ┌──────────────────┐    ┌──────────────────┐   │
│  │  Gemini 2.0 Flash│◄──►│  Tool Call Loop  │   │
│  │  (google-genai)  │    │  (up to 15 iters)│   │
│  └──────────────────┘    └────────┬─────────┘   │
└───────────────────────────────────┼─────────────┘
                                    │ function calls
                                    ▼
                    ┌───────────────────────────────┐
                    │  GitLab MCP Server (npx)      │
                    │  @gitlab-org/mcp-gitlab        │
                    │                               │
                    │  list_pipelines               │
                    │  get_pipeline_jobs            │
                    │  get_job_log                  │
                    │  create_note (MR comment)     │
                    └───────────────────────────────┘
                                    │
                                    ▼
                            GitLab API (HTTPS)
```

**Fallback mode** (`--direct`): skips the MCP server and uses `python-gitlab` directly — useful when Node.js is unavailable.

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/64johnlee/hackathon-pipeline-guard
cd hackathon-pipeline-guard
pip install -e .
```

Node.js >=18 is required for the GitLab MCP server (primary mode). Skip with `--direct` if unavailable.

### 2. Configure

```bash
cp .env.example .env
# Edit .env — choose one auth mode:
#   AI Studio:  GEMINI_API_KEY  — https://aistudio.google.com/
#   Vertex AI:  GCP_PROJECT + GCP_LOCATION (see "Agent Builder" section below)
#
#   GITLAB_TOKEN  — GitLab PAT with api + read_repository scopes
```

### 3. Diagnose a failed pipeline

```bash
# Latest failed pipeline in a project
pipelineguard diagnose myorg/myrepo

# Specific pipeline ID
pipelineguard diagnose myorg/myrepo --pipeline 42

# Also post a comment on the MR
pipelineguard diagnose myorg/myrepo --comment

# Skip MCP server (direct API mode)
pipelineguard diagnose myorg/myrepo --direct
```

### 4. Watch mode (continuous monitoring)

```bash
# Poll every 60s, auto-comment on new failures
pipelineguard watch myorg/myrepo --interval 60 --comment
```

### 5. Webhook server (fully automated)

Run PipelineGuard as a persistent service that receives GitLab pipeline events:

```bash
# Install web extras
pip install 'pipelineguard[web]'

# Start the server
pipelineguard serve --port 8765 --comment
```

Then in GitLab: **Settings → Webhooks** → add `http://your-host:8765/webhook/gitlab`
with the **Pipeline events** trigger. Every failed pipeline is diagnosed automatically
and the result is posted as an MR comment — zero manual intervention.

Optional: set `WEBHOOK_SECRET` env var + the same token in GitLab for request validation.

```bash
# Test with the included example payload
curl -X POST http://localhost:8765/webhook/gitlab \
  -H "Content-Type: application/json" \
  -d @demo/webhook_payload_example.json
# → {"status":"diagnosed","root_cause":"Missing REDIS_URL...","category":"env_var_missing"}
```

---

## Deploy to Cloud Run (hosted URL)

The fastest way to get a live, public endpoint for the hackathon submission:

```bash
export GCP_PROJECT=my-gcp-project
export GITLAB_TOKEN=glpat-...
# optional: export GEMINI_API_KEY=... (uses AI Studio; omit to use Vertex AI)
# optional: export WEBHOOK_SECRET=my-secret

bash deploy_cloudrun.sh
```

The script:
1. Creates an Artifact Registry repo
2. Builds the container with **Cloud Build**
3. Stores secrets in **Secret Manager**
4. Deploys to **Cloud Run** (min 0 → scales to 0 when idle, free tier friendly)
5. Prints the live URL

```
======================================================
  PipelineGuard deployed!
  URL:      https://pipeline-guard-xxxx-uc.a.run.app
  Webhook:  https://pipeline-guard-xxxx-uc.a.run.app/webhook/gitlab
  Health:   https://pipeline-guard-xxxx-uc.a.run.app/health
======================================================
```

Then in GitLab: **Settings → Webhooks** → paste the webhook URL, enable **Pipeline events**.

---

## Google Cloud Agent Builder (Vertex AI)

PipelineGuard runs natively on **Vertex AI Agent Engine** (Reasoning Engine), the managed
serving platform in Google Cloud Agent Builder.  This gives you a scalable, serverless
deployment without managing containers.

### Run locally with Vertex AI backend

Instead of an API key, authenticate with your GCP project:

```bash
gcloud auth application-default login

# Set env vars
export GCP_PROJECT=my-gcp-project
export GCP_LOCATION=us-central1
export GITLAB_TOKEN=glpat-...

# Same CLI — just add --vertex
pipelineguard diagnose myorg/myrepo --vertex
pipelineguard serve --vertex --port 8765
```

### Deploy to Agent Engine

```bash
pip install 'pipelineguard[vertex]'

pipelineguard deploy \
  --gcp-project my-gcp-project \
  --gcp-location us-central1 \
  --gitlab-token glpat-...
```

This packages PipelineGuard as a **Reasoning Engine** resource in your project.  Once
deployed you can query it from any Google Cloud environment — Cloud Run, Cloud Functions,
other agents — without shipping your own container:

```python
import vertexai
from vertexai.preview import reasoning_engines

vertexai.init(project="my-gcp-project", location="us-central1")
app = reasoning_engines.ReasoningEngine("projects/.../reasoningEngines/...")
result = app.query(project="myorg/myrepo")
print(result["root_cause"])
```

Or use the Python API directly to deploy programmatically:

```python
from pipelineguard.vertex_agent import PipelineGuardVertexApp

app = PipelineGuardVertexApp(gitlab_token="glpat-...", gcp_project="my-project")
app.set_up()
result = app.query(project="myorg/myrepo")
```

---

## Example Output

See [`demo/sample_output.txt`](demo/sample_output.txt) for a full annotated terminal session.

```
╭─ PipelineGuard · project myorg/backend · latest failed ─╮
│ mode: MCP                                                │
╰──────────────────────────────────────────────────────────╯
  → list_pipelines({"project_id": "myorg/backend"})
  → get_pipeline_jobs({"pipeline_id": 12847})
  → get_job_log({"job_id": 98231})

╭─ Diagnosis ─────────────────────────────────────────────╮
│ Root cause: ModuleNotFoundError: No module named         │
│ 'pydantic_v1'. pydantic v2 removed the v1 shim;         │
│ pin pydantic<2.0 or add pydantic[v1] to requirements.   │
│ Category: missing_dependency                             │
│ Affected jobs: test, integration-test                    │
╰──────────────────────────────────────────────────────────╯

Proposed fix for requirements.txt (high confidence):
  Pin pydantic to <2.0 or add pydantic[v1] shim

diff:
-pydantic>=1.9
+pydantic>=1.9,<2.0
```

---

## How It Works

1. **MCP mode** (primary): PipelineGuard starts `@gitlab-org/mcp-gitlab` as a subprocess. Gemini 2.0 Flash receives the MCP server's tools as `FunctionDeclaration` objects and autonomously decides which to call — listing pipelines, fetching job logs, reading `.gitlab-ci.yml` — until it has enough context to diagnose the failure.

2. **Structured output**: The system prompt instructs Gemini to produce a natural-language explanation followed by a machine-readable JSON block, parsed into a typed `DiagnosisReport` with `FixProposal` objects.

3. **Direct mode** (fallback): All data is fetched upfront via `python-gitlab` and packed into a single Gemini prompt.

---

## Failure Categories

| Category | Example |
|---|---|
| `missing_dependency` | `ModuleNotFoundError`, `apt-get: not found` |
| `env_var_missing` | `KeyError: 'DATABASE_URL'`, secret not injected |
| `config_error` | Invalid `.gitlab-ci.yml`, bad Docker image tag |
| `flaky_test` | Network timeout, random seed, timing assertion |
| `logic_bug` | `AssertionError`, wrong expected value |
| `infrastructure` | OOM kill, disk full, runner unavailable |
| `permissions` | `EACCES`, HTTP 403, cannot write to path |

---

## Tech Stack

| Component | Library |
|---|---|
| LLM | Gemini 2.0 Flash via `google-genai` |
| GitLab tools | `@gitlab-org/mcp-gitlab` MCP server |
| MCP client | `mcp` (official Python SDK) |
| GitLab fallback | `python-gitlab` |
| CLI | `click` + `rich` |
| Webhook server | `FastAPI` + `uvicorn` |

---

## License

MIT
