# PipelineGuard

> AI-powered GitLab CI pipeline diagnostics using Gemini 2.5 Flash + a purpose-built MCP server.

PipelineGuard watches your GitLab CI pipelines. When one fails, it:

1. **Fetches** job logs via a bundled stdio MCP server (`pipelineguard.mcp_server`)
2. **Analyzes** root cause with Gemini 2.5 Flash (not just "build failed" — the *exact* reason)
3. **Proposes** a targeted fix with a unified diff
4. **Comments** the findings on the associated merge request

Verified end-to-end against a real failed `gitlab-org/cli` pipeline: **~46 seconds, 2 tool calls, correct root cause identified** (config error: malformed git ref). The agentic loop terminates well under its 15-iteration safety cap.

Built for the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com) — GitLab track.

> **Looking for the Splunk side?** This repo also ships **SplunkGuard** — a Gemini agent driven by the official Splunk MCP Server (Splunkbase App #7931) for natural-language observability investigations. See [SPLUNK.md](./SPLUNK.md) (submitted to the [Splunk Agentic Ops Hackathon](https://splunk.devpost.com/) — Observability track).

---

## Architecture

```
User / CI Webhook
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│  PipelineGuardAgent  (pipelineguard/agent.py)                     │
│                                                                   │
│  ┌──────────────────┐    ┌─────────────────────────────────────┐  │
│  │  Gemini 2.5 Flash│◄──►│  Tool Call Loop   (≤15 iterations)  │  │
│  │  (Vertex AI /    │    │  Routes by tool name prefix:        │  │
│  │   AI Studio)     │    │    gl_*  →  Official GitLab MCP     │  │
│  └──────────────────┘    │    rest  →  PipelineGuard MCP       │  │
│                           └────────────┬──────────┬────────────┘  │
└────────────────────────────────────────┼──────────┼───────────────┘
                                         │          │
               ┌─────────────────────────┘          └────────────────────────┐
               │ StreamableHTTP (HTTPS)                   stdio (subprocess)  │
               ▼                                          ▼
┌──────────────────────────────────┐   ┌──────────────────────────────────────┐
│  Official GitLab MCP Server      │   │  pipelineguard.mcp_server (bundled)  │
│  gitlab.com/api/v4/mcp           │   │                                      │
│  Auth: Bearer <PAT>              │   │  list_pipelines                      │
│  Tool prefix: gl_                │   │  get_pipeline_jobs                   │
│                                  │   │  get_job_log                         │
│  gl_list_projects                │   │  find_merge_request_by_sha           │
│  gl_get_project                  │   │  create_merge_request_note           │
│  gl_list_merge_requests          │   └──────────────────────────────────────┘
│  gl_list_pipelines  …            │                     │
└──────────────────────────────────┘                     │
               │                                         │
               └────────────────────┬────────────────────┘
                                    ▼
                            GitLab API (HTTPS)
```

**Dual MCP architecture**: Gemini receives tools from *both* MCP servers simultaneously. The **official GitLab MCP server** (partner-required for the hackathon track) provides general project, MR, and pipeline context. PipelineGuard's **bundled pipeline MCP server** adds deep diagnosis tooling not yet in the official server — job log retrieval, structured failure categorisation, and MR note posting. Tool calls are routed by name prefix: `gl_*` goes to the official server, everything else to the bundled one. If the official server is unreachable, diagnosis continues uninterrupted with the bundled server.

**Fallback mode** (`--direct`): skips both MCP servers and uses `python-gitlab` directly in-process — single Gemini call instead of an agentic loop. Useful when MCP stdio subprocesses aren't allowed by the host (e.g. some sandboxed CI runners).

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/64johnlee/hackathon-pipeline-guard
cd hackathon-pipeline-guard
pip install -e .
```

No external services to install — the MCP server is a Python module that ships with the package. `pip install` is all you need (Python ≥ 3.10).

### 2. Configure

```bash
cp .env.example .env
# Edit .env — choose one auth mode:
#   AI Studio:  GEMINI_API_KEY  — https://aistudio.google.com/
#   Vertex AI:  GCP_PROJECT + GCP_LOCATION (see "Agent Builder" section below)
#
#   GITLAB_TOKEN  — GitLab PAT with api + read_repository scopes
#                   (also exported as GITLAB_PERSONAL_ACCESS_TOKEN to the MCP server)
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

1. **MCP mode** (primary): PipelineGuard spawns `pipelineguard.mcp_server` as a stdio subprocess (`python -m pipelineguard.mcp_server`). The server exposes 5 GitLab pipeline tools — `list_pipelines`, `get_pipeline_jobs`, `get_job_log`, `find_merge_request_by_sha`, `create_merge_request_note` — implemented on top of `python-gitlab`. Gemini 2.5 Flash receives those tools as `FunctionDeclaration` objects and autonomously decides which to call until it has enough context to diagnose the failure. In our benchmark against `gitlab-org/cli` pipeline #2552952663, the loop terminated in 2 tool calls.

2. **Structured output**: The system prompt instructs Gemini to produce a natural-language explanation followed by a machine-readable JSON block, parsed into a typed `DiagnosisReport` with `FixProposal` objects. A regex extractor handles the occasional case where the model wraps the JSON in stray prose.

3. **Direct mode** (`--direct`): All pipeline data is fetched upfront with `python-gitlab` in-process and packed into a single Gemini call — no MCP subprocess, no agentic loop. Same diagnostic quality, ~7s faster, but loses the per-tool granularity that MCP provides for tracing and reuse.

4. **Why a bundled MCP server?** GitLab does not yet ship an official MCP server with pipeline-introspection tools. Rather than depend on third-party packages with mismatched tool surfaces, PipelineGuard ships its own — minimal, purpose-built for the agent that consumes it, and reusable from any MCP-compatible client (Claude Desktop, Cursor, etc.).

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
| LLM | Gemini 2.5 Flash via `google-genai` (AI Studio or Vertex AI) |
| Cloud deployment | Cloud Run + Artifact Registry; Vertex AI Agent Engine for hosted agent |
| MCP server | `pipelineguard.mcp_server` (bundled, FastMCP / Python SDK) |
| MCP client | `mcp` (official Python SDK) |
| GitLab API | `python-gitlab` (used by both MCP server and `--direct` fallback) |
| CLI | `click` + `rich` |
| Webhook server | `FastAPI` + `uvicorn` |

---

## License

MIT
