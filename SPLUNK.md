# SplunkGuard

> AI-powered Splunk observability investigations: ask a natural-language question, Gemini 2.5 Flash drives the official Splunk MCP Server to find the answer.

**Submitted to:** [Splunk Agentic Ops Hackathon](https://splunk.devpost.com/) — **Observability** track (with eyes on the **Best Use of Splunk MCP Server** prize).

SplunkGuard is a Gemini-driven agent that investigates operational questions against your Splunk data. Ask *"Why did pipeline 12345 fail last night?"* or *"Are there auth anomalies in the last 24h?"* — Gemini autonomously picks Splunk MCP tools (`splunk_run_query`, `get_indexes`, `splunk_run_saved_search`, etc.), iterates until it has enough context, and returns a structured `SplunkInvestigationReport` with root cause + recommended actions.

---

## Architecture

```
User question (natural language)
      │
      ▼
┌──────────────────────────────────────────────────┐
│  SplunkGuardAgent  (pipelineguard/splunk_agent)  │
│                                                  │
│  ┌──────────────────┐   ┌──────────────────────┐ │
│  │ Gemini 2.5 Flash │◄──┤  Tool-call loop      │ │
│  │ (google-genai)   │   │  (≤15 iterations)    │ │
│  └──────────────────┘   └──────────┬───────────┘ │
└────────────────────────────────────┼─────────────┘
                                     │ MCP function calls
                                     │   (HTTP/SSE)
                                     ▼
                  ┌──────────────────────────────────┐
                  │  Splunk MCP Server               │
                  │  (Splunkbase App #7931, official)│
                  │                                  │
                  │  splunk_run_query                │
                  │  splunk_run_saved_search         │
                  │  get_indexes                     │
                  │  get_index_info                  │
                  │  saia_generate_spl  (optional)   │
                  │  saia_ask_splunk_question  (opt) │
                  └──────────────────┬───────────────┘
                                     │ SPL searches over indexed events
                                     ▼
                  ┌──────────────────────────────────┐
                  │  Splunk Enterprise / Cloud       │
                  │  - Indexed CI/CD logs            │
                  │  - Saved searches                │
                  │  - Metrics & events              │
                  └──────────────────────────────────┘

Fallback path (--direct): skips MCP, calls Splunk REST API jobs endpoint
directly via python-httpx, packs a sample of events into a single Gemini call.
Useful for sandboxed environments where the MCP Server App isn't installed.

Ingestion path (CI/CD → Splunk):  pipelineguard/ingesters/gitlab_to_splunk.py
  GitLab API → batched HEC events (sourcetype=gitlab:pipeline / gitlab:job)
  → Splunk index "pipelineguard" → queryable by SplunkGuardAgent.
```

---

## Quick Start

### 1. Install Splunk Enterprise (free trial)

```bash
# Linux/macOS — fastest path is the Splunk Free single-instance Docker image
docker run -d -p 8000:8000 -p 8088:8088 -p 8089:8089 \
  -e SPLUNK_PASSWORD=changeme -e SPLUNK_START_ARGS=--accept-license \
  --name splunk splunk/splunk:latest

# Wait ~60s for boot, then open http://localhost:8000  (admin / changeme)
```

### 2. Install the Splunk MCP Server app

Inside Splunk Web → **Apps** → **Find More Apps** → search **"Splunk MCP Server"** → install (Splunkbase App ID `7931`, beta).

After install, open the app once to generate an **encrypted MCP token** (the app's own UI walks you through it).

### 3. Install PipelineGuard

```bash
git clone https://github.com/64johnlee/hackathon-pipeline-guard
cd hackathon-pipeline-guard
pip install -e .
```

### 4. Configure

```bash
cp .env.example .env
# Edit .env:
#   GEMINI_API_KEY=...                                    # AI Studio key
#   SPLUNK_MCP_TOKEN=...                                  # from step 2
#   SPLUNK_MCP_URL=https://localhost:8089/services/mcp    # default
```

### 5. (Optional) Ingest sample CI/CD logs

If you don't have CI/CD data in Splunk yet, pump some GitLab data in:

```bash
# Requires GITLAB_TOKEN (api + read_repository scopes) and SPLUNK_HEC_TOKEN
pipelineguard splunk ingest --project myorg/myrepo --since -7d
```

This populates Splunk's `pipelineguard` index with `gitlab:pipeline` and
`gitlab:job` events (with log tails on failed/canceled jobs) so SplunkGuard
has real data to investigate.

### 6. Investigate

```bash
# Natural-language question over the last 24h:
pipelineguard splunk investigate "What CI pipelines failed last night and why?"

# Over a specific window:
pipelineguard splunk investigate "Find auth anomalies" --earliest -6h --latest now

# Bypass MCP, use Splunk REST directly:
pipelineguard splunk investigate "Disk full warnings?" --direct
```

Output is a structured `SplunkInvestigationReport`:

```
╭─────────────────────────────────────────────────────────────────────╮
│ SplunkGuard · What CI pipelines failed last night and why?          │
│ time range: -24h → now · mode: MCP                                  │
╰─────────────────────────────────────────────────────────────────────╯
  → get_indexes({})
  → splunk_run_query({"query": "search index=pipelineguard sourcetype=gitlab:job status=failed earliest=-24h | stats count by failure_reason, name"})
  → splunk_run_query({"query": "search index=pipelineguard sourcetype=gitlab:job status=failed name=test-unit earliest=-24h | head 5 | table _time, project, log_tail"})

╭─ Diagnosis ─────────────────────────────────────────────────────────╮
│ Root cause: 3 failed test-unit jobs in myorg/api-service all share  │
│ the same ModuleNotFoundError for `pydantic_v1` after the v2 upgrade │
│ in commit 4f8b2a1. Category: pipeline_failure.                      │
╰─────────────────────────────────────────────────────────────────────╯

Recommended actions:
  - Pin pydantic<2.0 in requirements.txt          (high confidence)
  - Add saved search: alert on >2 test-unit fails / 15min  (medium)
```

---

## CLI reference

| Command | What it does |
|---|---|
| `pipelineguard splunk investigate "<question>"` | Run an investigation. Default mode: MCP. Add `--direct` to skip MCP. |
| `pipelineguard splunk investigate ... --earliest -6h --latest now` | Restrict the time window. |
| `pipelineguard splunk ingest --project myorg/myrepo` | Pump GitLab pipelines + jobs into Splunk via HEC. |
| `pipelineguard splunk ingest --project ... --since -7d` | Backfill 7 days of pipeline history. |

---

## Configuration

| Env var | What | Required |
|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio key (free tier OK) | Yes (or use `--vertex` for Vertex AI) |
| `SPLUNK_MCP_TOKEN` | Encrypted token from Splunk MCP Server App UI | Yes (for MCP mode) |
| `SPLUNK_MCP_URL` | Splunk MCP endpoint (default `https://localhost:8089/services/mcp`) | No (defaults shown) |
| `SPLUNK_HEC_TOKEN` | HTTP Event Collector token (for `ingest` command only) | Only for ingest |
| `SPLUNK_HEC_URL` | HEC endpoint (default `https://localhost:8088`) | No |

For self-signed certs in local Splunk dev instances, pass `--no-verify-ssl` to skip TLS verification (the MCP backend now honors this — fixed in commit after audit).

---

## Why this submission targets two prizes

| Prize | Why we qualify |
|---|---|
| **Observability** track ($3,000) | SplunkGuard's primary use case is CI/CD failure triage — classic observability problem. Real-world demo: GitLab pipeline logs ingested via HEC → indexed in Splunk → investigated via natural language. |
| **Best Use of Splunk MCP Server** ($1,000) | MCP-first by design. Splunkbase App #7931 is the primary integration path. Tool discovery is fully dynamic (the agent picks tools from the server's advertised list, not hardcoded names) — exactly how MCP is meant to be consumed. |

Maximum payout: **$4,000** (track + best-use). Grand Prize ($7,000) and other "Best Use" prizes (Hosted Models, Developer Tools) are also possible but not the primary target.

---

## License

MIT — same as the rest of the project.
